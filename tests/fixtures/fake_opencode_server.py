from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


SESSIONS: dict[str, dict[str, Any]] = {}


class FakeOpenCodeHandler(BaseHTTPRequestHandler):
    server_version = "FakeOpenCode/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/global/health":
            self._json(200, {"healthy": True, "version": "fake-opencode"})
            return

        directory = self._directory_from_query(parsed.query)
        if directory is None:
            self._json(400, {"error": "missing directory query"})
            return
        if path == "/path":
            self._json(200, {"path": directory})
            return
        if path in {"/project/current", "/config", "/vcs"}:
            self._json(200, {"directory": directory})
            return
        if path == "/file/status":
            self._json(200, [])
            return
        if path == "/session/status":
            self._json(200, {session_id: {"type": "idle"} for session_id in SESSIONS})
            return

        parts = path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "session":
            session_id = parts[1]
            session = SESSIONS.get(session_id)
            if session is None:
                self._json(404, {"error": "unknown session"})
                return
            if len(parts) == 2:
                self._json(200, session["session"])
                return
            if len(parts) == 3 and parts[2] == "message":
                self._json(200, session.get("messages", []))
                return
            if len(parts) == 3 and parts[2] == "children":
                self._json(200, [])
                return
            if len(parts) == 3 and parts[2] == "todo":
                self._json(200, [])
                return
            if len(parts) == 3 and parts[2] == "diff":
                self._json(200, {"files": ["fake-opencode-output.txt"]})
                return
        self._json(404, {"error": f"unhandled GET {path}"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        directory = self.headers.get("x-opencode-directory")
        if directory is None:
            self._json(400, {"error": "missing x-opencode-directory"})
            return
        cwd = unquote(directory)
        body = self._read_json()

        if path == "/session":
            session_id = f"ses_{len(SESSIONS) + 1}"
            session = {
                "id": session_id,
                "directory": cwd,
                "title": body.get("title", ""),
                "version": "fake-opencode",
                "parentID": None,
            }
            SESSIONS[session_id] = {"session": session, "messages": []}
            self._json(200, session)
            return

        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "session" and parts[2] == "message":
            session_id = parts[1]
            if session_id not in SESSIONS:
                self._json(404, {"error": "unknown session"})
                return
            prompt_text = "\n".join(
                part.get("text", "") for part in body.get("parts", []) if part.get("type") == "text"
            )
            Path(cwd, "fake-opencode-output.txt").write_text(
                f"fake opencode handled prompt:\n{prompt_text}\n",
                encoding="utf-8",
            )
            SESSIONS[session_id]["messages"] = [
                {"role": "user", "parts": body.get("parts", [])},
                {
                    "role": "assistant",
                    "parts": [
                        {
                            "type": "text",
                            "text": "fake opencode completed the evaluation",
                        }
                    ],
                },
            ]
            self._json(200, {"ok": True})
            return
        if len(parts) == 3 and parts[0] == "session" and parts[2] == "abort":
            self._json(204, {})
            return
        self._json(404, {"error": f"unhandled POST {path}"})

    def _directory_from_query(self, query: str) -> str | None:
        values = parse_qs(query).get("directory")
        if not values:
            return None
        return values[0]

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _json(self, status: int, value: Any) -> None:
        payload = b"" if status == 204 else json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4096)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), FakeOpenCodeHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
