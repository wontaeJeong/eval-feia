from __future__ import annotations

import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest


TEAM_CONFIG = {
    "provider": "autogen_agentchat.teams.RoundRobinGroupChat",
    "component_type": "team",
    "config": {
        "participants": [
            {
                "name": "knox_mail_report_agent",
                "model_client": {"provider": "placeholder", "model": "placeholder"},
                "tools": ["web_search", "mail_report_draft"],
                "system_message": "Search the web, summarize findings, and prepare a Knox mail report without real credentials.",
            }
        ],
        "termination_condition": {"type": "TextMentionTermination", "text": "DONE"},
    },
}


def make_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=path, check=True, capture_output=True, text=True)
    return path


class FakeOpenCodeHandler(BaseHTTPRequestHandler):
    def fake_server(self) -> FakeOpenCodeServer:
        return cast(FakeOpenCodeServer, self.server)

    def log_message(self, format: str, *_args: Any) -> None:
        _ = format
        return

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        server = self.fake_server()
        server.calls.append(("GET", parsed.path))
        if parsed.path == "/global/health":
            index = min(server.health_count, len(server.versions) - 1)
            server.health_count += 1
            self._json({"healthy": server.healthy, "version": server.versions[index]})
            return
        if parsed.path == "/path":
            if server.path_returns_empty:
                self._json({})
            else:
                cwd = parse_qs(parsed.query).get("directory", [server.cwd])[0] if server.echo_directory else server.cwd
                self._json({"cwd": cwd})
            return
        if parsed.path == "/project/current":
            if server.project_returns_empty:
                self._json({})
                return
            cwd = parse_qs(parsed.query).get("directory", [server.cwd])[0] if server.echo_directory else server.cwd
            self._json({"project": {"root": cwd}})
            return
        if parsed.path == "/event":
            server.sse_connected = True
            if server.sse_after_prompt_events:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b'event: message\ndata: {"type":"server.connected","properties":{}}\n\n')
                self.wfile.flush()
                deadline = time.monotonic() + 2
                while server.prompt_count == 0 and time.monotonic() < deadline:
                    time.sleep(0.01)
                for event in server.sse_after_prompt_events:
                    body = f"event: message\ndata: {json.dumps(event)}\n\n".encode("utf-8")
                    self.wfile.write(body)
                    self.wfile.flush()
                return
            body = b'event: message\ndata: {"type":"server.connected","properties":{}}\n\n'
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/session/status":
            self._json({"session-1": {"status": "idle"}})
            return
        if parsed.path == "/session/session-1/children":
            self._json([])
            return
        if parsed.path == "/session/session-1/todo":
            self._json([])
            return
        if parsed.path == "/session/session-1/diff":
            body = b"diff --git a/team.json b/team.json\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/session/session-1/message":
            self._json([])
            return
        self._json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        server = self.fake_server()
        server.calls.append(("POST", parsed.path))
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        server.posts.append((parsed.path, json.loads(body.decode("utf-8") or "{}")))
        if parsed.path == "/session":
            self._json({"id": "session-1"})
            return
        if parsed.path == "/session/session-1/prompt_async":
            server.prompt_count += 1
            server.prompt_after_sse = server.sse_connected
            directory = parse_qs(parsed.query).get("directory", [None])[0]
            if directory:
                Path(directory, "team.json").write_text(json.dumps(TEAM_CONFIG, ensure_ascii=False), encoding="utf-8")
            self.send_response(204)
            self.end_headers()
            return
        self._json({"error": "not found"}, status=404)


class FakeOpenCodeServer(ThreadingHTTPServer):
    def __init__(
        self,
        cwd: str,
        versions: list[str] | None = None,
        healthy: bool = True,
        path_returns_empty: bool = False,
        project_returns_empty: bool = False,
        echo_directory: bool = False,
        sse_after_prompt_events: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(("127.0.0.1", 0), FakeOpenCodeHandler)
        self.cwd = cwd
        self.versions = versions or ["1.4.6"]
        self.healthy = healthy
        self.path_returns_empty = path_returns_empty
        self.project_returns_empty = project_returns_empty
        self.echo_directory = echo_directory
        self.sse_after_prompt_events = sse_after_prompt_events or []
        self.health_count = 0
        self.calls: list[tuple[str, str]] = []
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.sse_connected = False
        self.prompt_after_sse = False
        self.prompt_count = 0
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> FakeOpenCodeServer:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=2)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    return make_git_repo(tmp_path / "repo")


@pytest.fixture()
def fake_server(tmp_path: Path):
    server = FakeOpenCodeServer(str(tmp_path)).start()
    try:
        yield server
    finally:
        server.stop()
