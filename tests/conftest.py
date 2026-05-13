from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

import pytest


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("fixture repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    return repo


class FakeOpenCodeState:
    def __init__(self, *, version_sequence: list[str] | None = None, cwd_sequence: list[str | None] | None = None):
        self.version_sequence = version_sequence or ["1.4.6"]
        self.cwd_sequence = cwd_sequence or [None]
        self.current_attempt = 0
        self.current_cwd: Path | None = None
        self.prompts: list[int] = []
        self.sessions: list[int] = []
        self.sse_connected: list[int] = []
        self.prompt_before_sse: list[int] = []
        self.starts = 0
        self.stops = 0
        self.lock = threading.Lock()

    def start_attempt(self, cwd: Path) -> int:
        with self.lock:
            self.starts += 1
            self.current_attempt = self.starts
            self.current_cwd = cwd
            return self.current_attempt

    def stop_attempt(self) -> None:
        with self.lock:
            self.stops += 1

    def version(self) -> str:
        index = max(0, min(self.current_attempt - 1, len(self.version_sequence) - 1))
        return self.version_sequence[index]

    def cwd(self) -> str:
        index = max(0, min(self.current_attempt - 1, len(self.cwd_sequence) - 1))
        configured = self.cwd_sequence[index]
        if configured is not None:
            return configured
        assert self.current_cwd is not None
        return str(self.current_cwd)

    def write_artifact(self) -> None:
        assert self.current_cwd is not None
        artifact = {
            "provider": "autogen",
            "component_type": "team",
            "participants": [
                {
                    "name": "knox_mail_report_agent",
                    "model_client": {"provider": "openai", "model": "gpt-5.5"},
                    "tools": ["web_search", "mail_report_draft"],
                    "system_message": "Search the web, summarize findings, prepare a Knox mail report, and use a mail abstraction without credentials.",
                }
            ],
            "termination_condition": {"type": "max_messages", "max_messages": 6},
        }
        (self.current_cwd / "team.json").write_text(json.dumps(artifact), encoding="utf-8")


class FakeOpenCodeServer:
    def __init__(self, state: FakeOpenCodeState):
        self.state = state
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = cast(tuple[str, int], self.httpd.server_address)
        return f"http://{host}:{port}"

    def start(self) -> "FakeOpenCodeServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _json(self, payload: Any, status: int = 200) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path == "/global/health":
                    self._json({"healthy": True, "version": state.version()})
                elif self.path == "/path":
                    self._json({"cwd": state.cwd()})
                elif self.path == "/project/current":
                    self._json({"project": {"path": state.cwd()}})
                elif self.path == "/session/status":
                    self._json({"session-1": {"status": "idle"}})
                elif self.path.endswith("/children"):
                    self._json([])
                elif self.path.endswith("/todo"):
                    self._json([{"content": "draft report", "status": "completed"}])
                elif self.path.endswith("/message"):
                    self._json([])
                elif self.path.endswith("/diff"):
                    body = b""
                    self.send_response(200)
                    self.send_header("content-type", "text/plain")
                    self.send_header("content-length", "0")
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path in {"/event", "/global/event"}:
                    state.sse_connected.append(state.current_attempt)
                    self.send_response(200)
                    self.send_header("content-type", "text/event-stream")
                    self.send_header("cache-control", "no-cache")
                    self.end_headers()
                    events = [
                        ("server.connected", {"type": "server.connected"}),
                        ("message.updated", {"type": "message.updated"}),
                        ("tool.call.started", {"type": "tool.call.started"}),
                        ("tool.call.completed", {"type": "tool.call.completed"}),
                    ]
                    for event, data in events:
                        self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        time.sleep(0.01)
                else:
                    self._json({"error": "not found", "path": self.path}, status=404)

            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", "0"))
                if length:
                    self.rfile.read(length)
                if self.path == "/session":
                    state.sessions.append(state.current_attempt)
                    self._json({"id": "session-1"})
                elif self.path.endswith("/prompt_async"):
                    if state.current_attempt not in state.sse_connected:
                        state.prompt_before_sse.append(state.current_attempt)
                    state.prompts.append(state.current_attempt)
                    state.write_artifact()
                    self.send_response(204)
                    self.send_header("content-length", "0")
                    self.end_headers()
                elif self.path.endswith("/message"):
                    self._json({"ok": True})
                else:
                    self._json({"error": "not found", "path": self.path}, status=404)

        return Handler


@pytest.fixture
def fake_server() -> Generator[tuple[FakeOpenCodeServer, FakeOpenCodeState], None, None]:
    state = FakeOpenCodeState()
    server = FakeOpenCodeServer(state).start()
    try:
        yield server, state
    finally:
        server.stop()
