from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


VALID_TEAM: dict[str, Any] = {
    "provider": "autogen_agentchat.teams.RoundRobinGroupChat",
    "component_type": "team",
    "version": 1,
    "component_version": 1,
    "config": {
        "participants": [
            {
                "provider": "autogen_agentchat.agents.AssistantAgent",
                "component_type": "agent",
                "config": {
                    "name": "knox_mail_report_agent",
                    "model_client": {
                        "provider": "autogen_ext.models.openai.OpenAIChatCompletionClient",
                        "component_type": "model",
                        "config": {"model": "gpt-5.5"},
                    },
                    "tools": ["web_search", "mail_draft"],
                    "system_message": "Search the web, summarize findings, and prepare a Knox mail report.",
                },
            }
        ],
        "termination_condition": {
            "provider": "autogen_agentchat.conditions.TextMentionTermination",
            "component_type": "termination",
            "config": {"text": "TERMINATE"},
        },
    },
}


@dataclass(slots=True)
class FakeOpenCodeState:
    version_sequence: list[str]
    cwd_sequence: list[str]
    expected_cwd: str
    health_delay: float = 0.0
    sse_status: int = 200
    sse_close_after_headers: bool = False
    sse_keep_open_seconds: float = 0.5
    prompt_count: int = 0
    session_count: int = 0
    sse_connected_at: float | None = None
    prompt_at: float | None = None
    health_count: int = 0
    cwd_count: int = 0
    prompts_by_attempt: list[int] = field(default_factory=lambda: [0])

    @property
    def attempt_index(self) -> int:
        return min(max(self.health_count - 1, 0), max(len(self.version_sequence) - 1, 0))


class FakeOpenCodeServer:
    def __init__(self, state: FakeOpenCodeState) -> None:
        self.state = state
        handler = self._make_handler(state)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host = self.server.server_address[0]
        port = self.server.server_address[1]
        return f"http://{host}:{port}"

    def __enter__(self) -> "FakeOpenCodeServer":
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @staticmethod
    def _make_handler(state: FakeOpenCodeState):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/global/health":
                    if state.health_delay:
                        time.sleep(state.health_delay)
                    state.health_count += 1
                    attempt = state.attempt_index
                    version = state.version_sequence[min(attempt, len(state.version_sequence) - 1)]
                    self._json({"healthy": True, "version": version})
                    return
                if self.path == "/path":
                    state.cwd_count += 1
                    attempt = min(max(state.cwd_count - 1, 0), len(state.cwd_sequence) - 1)
                    self._json({"cwd": state.cwd_sequence[attempt]})
                    return
                if self.path == "/project/current":
                    self._json({"project": {"path": state.expected_cwd}})
                    return
                if self.path == "/event" or self.path == "/global/event":
                    if state.sse_status != 200:
                        self.send_error(state.sse_status)
                        return
                    state.sse_connected_at = time.monotonic()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    if state.sse_close_after_headers:
                        return
                    for event, data in [
                        ("server.connected", {"type": "server.connected"}),
                        ("message.updated", {"type": "message.updated", "role": "assistant"}),
                        ("tool.call.started", {"type": "tool.call.started"}),
                        ("tool.call.completed", {"type": "tool.call.completed"}),
                    ]:
                        try:
                            self.wfile.write(f"event: {event}\n".encode())
                            self.wfile.write(("data: " + json.dumps(data) + "\n\n").encode())
                            self.wfile.flush()
                        except BrokenPipeError:
                            return
                        time.sleep(0.02)
                    time.sleep(state.sse_keep_open_seconds)
                    return
                if self.path == "/session/status":
                    self._json({"status": "idle"})
                    return
                if self.path.endswith("/children"):
                    self._json({"children": [{"id": "child-1", "status": "idle"}]})
                    return
                if self.path.endswith("/todo"):
                    self._json({"items": [{"status": "completed"}]})
                    return
                if self.path.endswith("/diff"):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"")
                    return
                if self.path.endswith("/message"):
                    self._json([{"role": "assistant", "content": "done"}])
                    return
                self.send_error(404)

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length", "0"))
                if length:
                    self.rfile.read(length)
                if self.path == "/session":
                    state.session_count += 1
                    self._json({"id": "session-1"}, status=201)
                    return
                if self.path.endswith("/prompt_async"):
                    state.prompt_count += 1
                    state.prompt_at = time.monotonic()
                    attempt = max(state.health_count - 1, 0)
                    while len(state.prompts_by_attempt) <= attempt:
                        state.prompts_by_attempt.append(0)
                    state.prompts_by_attempt[attempt] += 1
                    self.send_response(204)
                    self.end_headers()
                    return
                self.send_error(404)

            def _json(self, payload: Any, status: int = 200) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


def write_valid_team(worktree: Path) -> None:
    (worktree / "team.json").write_text(json.dumps(VALID_TEAM))
