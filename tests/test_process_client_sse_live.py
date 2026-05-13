# pyright: reportMissingImports=false
from __future__ import annotations

import json
from pathlib import Path
from typing import TextIO, cast

import httpx

from eval_feia.live import LiveStateStore
from eval_feia.models import CwdCheckStatus, VersionCheck
from eval_feia.opencode_client import OpenCodeClient, compare_version
from eval_feia.process import build_isolated_env, build_opencode_command, redacted_env_view
from eval_feia.reports import JSONLRenderer
from eval_feia.sse import parse_sse_lines


def test_command_builder_uses_pinned_bunx() -> None:
    assert build_opencode_command("1.4.6", 4096) == [
        "bunx",
        "-p",
        "opencode-ai@1.4.6",
        "opencode",
        "serve",
        "--hostname",
        "127.0.0.1",
        "--port",
        "4096",
    ]


def test_isolated_env_redacts_password_and_excludes_ambient_secret(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNRELATED_SECRET_TOKEN", "ambient-secret")
    env = build_isolated_env(tmp_path / "home", tmp_path / "tmp", password="secret")
    assert env["OPENCODE_SERVER_PASSWORD"] == "secret"
    assert "UNRELATED_SECRET_TOKEN" not in env
    redacted = redacted_env_view(env)
    assert redacted["OPENCODE_SERVER_PASSWORD"] == "<redacted>"
    assert "secret" not in json.dumps(redacted)


def test_command_builder_rejects_unpinned_versions() -> None:
    try:
        build_opencode_command("latest", 4096)
    except ValueError as exc:
        assert "exact semver" in str(exc)
    else:
        raise AssertionError("accepted an unpinned OpenCode version")


def test_http_client_auth_and_endpoints(tmp_path: Path) -> None:
    seen_auth: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization"))
        if request.url.path == "/global/health":
            return httpx.Response(200, json={"healthy": True, "version": "1.4.6"})
        if request.url.path == "/path":
            return httpx.Response(200, json={"cwd": str(tmp_path)})
        if request.url.path == "/session":
            return httpx.Response(201, json={"id": "session-1"})
        if request.url.path == "/session/session-1/prompt_async":
            return httpx.Response(204)
        if request.url.path == "/session/status":
            return httpx.Response(200, json={"status": "idle"})
        if request.url.path.endswith("/children"):
            return httpx.Response(200, json={"children": []})
        if request.url.path.endswith("/todo"):
            return httpx.Response(200, json={"items": []})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(base_url="http://test", auth=httpx.BasicAuth("opencode", "pw"), transport=transport)
    client = OpenCodeClient("http://test", "pw", client=http_client)
    assert client.health().reported_version == "1.4.6"
    assert client.check_cwd(tmp_path).status == CwdCheckStatus.OK
    assert client.create_session("title") == "session-1"
    client.send_prompt_async("session-1", "prompt", "openai", "gpt", "impl")
    assert client.session_status()["status"] == "idle"
    assert client.children("session-1") == {"children": []}
    assert client.todo("session-1") == {"items": []}
    assert all(header and header.startswith("Basic ") for header in seen_auth)


def test_version_compare() -> None:
    assert compare_version("1.4.6", "1.4.6") == VersionCheck.MATCH
    assert compare_version("1.4.6", "1.4.5") == VersionCheck.MISMATCH
    assert compare_version("1.4.6", None) == VersionCheck.UNKNOWN


def test_sse_parser_multiline_and_error_count() -> None:
    result = parse_sse_lines([
        "event: message.updated",
        'data: {"type":"message.updated",',
        'data: "role":"assistant"}',
        "",
        "event: bad",
        "data: not-json",
        "",
    ])
    assert result.events[0].event == "message.updated"
    assert result.events[0].data["role"] == "assistant"
    assert result.events[1].data == "not-json"
    assert result.errors == 1


def test_live_updates_and_jsonl_flush() -> None:
    store = LiveStateStore()
    state = store.update_from_sse("run-001", "message.updated", {"type": "message.updated"})
    state = store.update_from_sse("run-001", "tool.call.started", {"type": "tool.call.started"})
    state = store.update_from_polls("run-001", children={"children": [{"status": "idle"}]}, todo={"items": [{"status": "completed"}]})
    assert state.message_count == 1
    assert state.tool_call_count == 1
    assert state.child_session_count == 1
    assert state.todo_status == "done"

    class FlushStream:
        def __init__(self) -> None:
            self.data = ""
            self.flushed = 0

        def write(self, value: str) -> None:
            self.data += value

        def flush(self) -> None:
            self.flushed += 1

    stream = FlushStream()
    JSONLRenderer(cast(TextIO, stream)).emit({"type": "run_progress", "run_id": "run-001"})
    assert stream.flushed == 1
    assert json.loads(stream.data)["type"] == "run_progress"
