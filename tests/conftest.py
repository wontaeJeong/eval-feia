# pyright: reportMissingImports=false
from __future__ import annotations

import base64
import json
import subprocess
import threading
import time
from dataclasses import dataclass, field
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from eval_feia.process import ProcessHandle


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return repo


def valid_team_config() -> dict[str, Any]:
    return {
        "provider": "autogen_agentchat.teams.RoundRobinGroupChat",
        "component_type": "team",
        "participants": [
            {
                "provider": "autogen_agentchat.agents.AssistantAgent",
                "name": "knox_mail_report_agent",
                "model_client": {"provider": "OpenAIChatCompletionClient", "config": {"model": "gpt-4.1"}},
                "tools": [{"name": "web_search"}, {"name": "mail_report_draft"}],
                "system_message": "Search the web, summarize findings, and prepare a Knox mail report.",
            }
        ],
        "termination_condition": {"type": "MaxMessageTermination", "max_messages": 8},
    }


@dataclass
class FakeOpenCodeState:
    versions: list[str] = field(default_factory=lambda: ["1.4.6"])
    cwd_modes: list[str] = field(default_factory=lambda: ["match"])
    healthy: bool = True
    path_empty: bool = False
    project_current_works: bool = True
    write_artifact: bool = True
    child_ids: list[str] = field(default_factory=list)
    basic_user: str = "opencode"
    basic_password: str = "unused"
    start_count: int = 0
    stop_count: int = 0
    prompt_count: int = 0
    session_count: int = 0
    sse_connected: bool = False
    prompt_before_sse: bool = False
    order: list[str] = field(default_factory=list)
    prompt_at: float | None = None
    busy_for: float = 0.05

    def current_index(self) -> int:
        return max(0, self.start_count - 1)

    def current_version(self) -> str:
        index = min(self.current_index(), len(self.versions) - 1)
        return self.versions[index]

    def cwd_for(self, directory: str | None) -> str:
        index = min(self.current_index(), len(self.cwd_modes) - 1)
        mode = self.cwd_modes[index]
        if mode == "match" and directory:
            return directory
        return "/tmp/eval-feia-wrong-cwd"


class FakeOpenCodeServer:
    def __init__(self, state: FakeOpenCodeState | None = None) -> None:
        self.state = state or FakeOpenCodeState()
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.url = ""
        self.port = 0

    def start(self) -> "FakeOpenCodeServer":
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            server_version = "FakeOpenCode/0.1"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _query(self) -> dict[str, list[str]]:
                return parse_qs(urlparse(self.path).query)

            def _directory(self) -> str | None:
                query = self._query()
                values = query.get("directory")
                return values[0] if values else None

            def _send_json(self, status: int, body: Any) -> None:
                raw = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _send_text(self, status: int, body: str, content_type: str = "text/plain") -> None:
                raw = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _read_json(self) -> Any:
                length = int(self.headers.get("Content-Length", "0"))
                if length == 0:
                    return {}
                return json.loads(self.rfile.read(length).decode("utf-8"))

            def _authorized(self) -> bool:
                header = self.headers.get("Authorization", "")
                if not header.startswith("Basic "):
                    return False
                raw = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
                return raw.startswith("opencode:")

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if not self._authorized():
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="Secure Area"')
                    self.end_headers()
                    return
                if parsed.path == "/global/health":
                    self._send_json(200, {"healthy": state.healthy, "version": state.current_version()})
                    return
                if parsed.path == "/path":
                    if state.path_empty:
                        self._send_json(200, {"config": "/not-cwd/config"})
                    else:
                        self._send_json(200, {"directory": state.cwd_for(self._directory())})
                    return
                if parsed.path == "/project/current":
                    self._send_json(200, {"worktree": state.cwd_for(self._directory()) if state.project_current_works else None})
                    return
                if parsed.path in {"/global/event", "/event"}:
                    state.sse_connected = True
                    state.order.append("sse")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache, no-transform")
                    self.end_headers()
                    self.wfile.write(b'data: {"payload":{"type":"server.connected","properties":{}}}\n\n')
                    self.wfile.flush()
                    return
                if parsed.path == "/session/status":
                    active = state.prompt_at is not None and time.monotonic() - state.prompt_at < state.busy_for
                    status = {"ses-1": {"type": "busy" if active else "idle"}}
                    for child in state.child_ids:
                        status[child] = {"type": "idle"}
                    self._send_json(200, status)
                    return
                if parsed.path == "/session/ses-1/children":
                    self._send_json(200, [{"id": child, "title": child} for child in state.child_ids])
                    return
                if parsed.path == "/session/ses-1/todo":
                    self._send_json(200, [{"content": "write config", "status": "completed", "priority": "high"}])
                    return
                if parsed.path == "/session/ses-1/diff":
                    self._send_text(200, "")
                    return
                self._send_json(404, {"error": parsed.path})

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if not self._authorized():
                    self.send_response(401)
                    self.end_headers()
                    return
                if parsed.path == "/session":
                    self._read_json()
                    state.session_count += 1
                    self._send_json(200, {"id": "ses-1", "title": "eval-feia"})
                    return
                if parsed.path in {"/session/ses-1/prompt_async", "/session/ses-1/message"}:
                    self._read_json()
                    if not state.sse_connected:
                        state.prompt_before_sse = True
                    state.order.append("prompt")
                    state.prompt_count += 1
                    state.prompt_at = time.monotonic()
                    directory = self._directory()
                    if state.write_artifact and directory:
                        Path(directory, "team.json").write_text(json.dumps(valid_team_config()), encoding="utf-8")
                    self.send_response(204 if parsed.path.endswith("prompt_async") else 200)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self._send_json(404, {"error": parsed.path})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = int(self.httpd.server_address[1])
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)


@pytest.fixture()
def fake_opencode() -> Generator[FakeOpenCodeServer, None, None]:
    server = FakeOpenCodeServer().start()
    try:
        yield server
    finally:
        server.stop()


class FakeProcessManager:
    def __init__(self, server: FakeOpenCodeServer) -> None:
        self.server = server

    def start(self, command: list[str], cwd: Path, env: dict[str, str], log_path: Path, port: int) -> ProcessHandle:
        self.server.state.start_count += 1
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("fake opencode\n", encoding="utf-8")
        return ProcessHandle(None, 9000 + self.server.state.start_count, self.server.port, self.server.url, command)

    def stop(self, handle: ProcessHandle, timeout: float = 5.0) -> dict[str, bool]:
        self.server.state.stop_count += 1
        return {"terminated": True, "killed": False}
