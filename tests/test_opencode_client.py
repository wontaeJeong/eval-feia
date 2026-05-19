from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

import httpx

from eval_feia.opencode_client import (
    DIRECTORY_HEADER,
    OpencodeClient,
    build_opencode_prompt_request,
    encode_directory,
)


def test_build_prompt_request_uses_message_without_command() -> None:
    path, body = build_opencode_prompt_request(
        "ses_1",
        "hello",
        agent="build",
        model={"providerID": "p", "modelID": "m"},
    )

    assert path == "/session/ses_1/message"
    assert body == {
        "agent": "build",
        "model": {"providerID": "p", "modelID": "m"},
        "parts": [{"type": "text", "text": "hello"}],
    }
    assert "command" not in body
    assert "arguments" not in body


def test_build_prompt_request_uses_command_endpoint_with_arguments() -> None:
    path, body = build_opencode_prompt_request(
        "ses_1",
        "git status 확인해줘",
        command="bash",
        agent="build",
        model={"providerID": "p", "modelID": "m"},
    )

    assert path == "/session/ses_1/command"
    assert body == {
        "agent": "build",
        "arguments": "git status 확인해줘",
        "command": "bash",
        "model": "p/m",
    }
    assert "parts" not in body


def test_build_prompt_request_normalizes_leading_slash_command() -> None:
    path, body = build_opencode_prompt_request("ses_1", "echo hello", command="/bash")

    assert path == "/session/ses_1/command"
    assert body == {"arguments": "echo hello", "command": "bash"}


def test_build_prompt_request_treats_blank_command_as_message() -> None:
    for blank in ("", "   "):
        path, body = build_opencode_prompt_request("ses_1", "hello", command=blank)

        assert path == "/session/ses_1/message"
        assert body == {"parts": [{"type": "text", "text": "hello"}]}
        assert "command" not in body
        assert "arguments" not in body


def test_directory_encoding_is_exactly_once_for_get_and_post(tmp_path: Path) -> None:
    cwd = tmp_path / "repo with space" / "한글"
    encoded = encode_directory(cwd)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/path":
            return httpx.Response(200, json={"path": unquote(encoded)})
        if request.url.path == "/session":
            return httpx.Response(200, json={"id": "ses_1", "directory": unquote(encoded)})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = OpencodeClient("http://opencode.test", transport=httpx.MockTransport(handler))
    client.path(cwd)
    client.session_create(cwd, "eval-feia/run/cand-001")

    get_request, post_request = requests
    assert get_request.method == "GET"
    assert get_request.url.query.decode() == f"directory={encoded}"
    assert DIRECTORY_HEADER not in get_request.headers
    assert post_request.method == "POST"
    assert post_request.headers[DIRECTORY_HEADER] == encoded
    assert post_request.url.query == b""
    assert "%252F" not in str(get_request.url)
    assert "%252F" not in post_request.headers[DIRECTORY_HEADER]
    assert "한글" not in post_request.headers[DIRECTORY_HEADER]
    assert "%20" in encoded
    assert "%2F" in encoded


def test_rest_request_shapes_for_session_prompt_collect_and_abort(tmp_path: Path) -> None:
    cwd = tmp_path / "candidate"
    encoded = encode_directory(cwd)
    seen: list[tuple[str, str, str, dict[str, str], dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        json_body = None
        if request.content:
            json_body = json.loads(request.content.decode())
        seen.append(
            (
                request.method,
                request.url.path,
                request.url.query.decode(),
                dict(request.headers),
                json_body,
            )
        )
        if request.url.path == "/global/health":
            return httpx.Response(200, json={"healthy": True, "version": "test"})
        if request.url.path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": "ses_1"})
        if request.url.path == "/session/ses_1/message" and request.method == "POST":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/session/ses_1/abort":
            return httpx.Response(204)
        return httpx.Response(200, json=[])

    client = OpencodeClient("http://opencode.test", transport=httpx.MockTransport(handler))
    client.health()
    client.session_create(cwd, "eval-feia/run/cand-001")
    client.session_prompt(
        cwd,
        "ses_1",
        "hello",
        agent="build",
        model={"providerID": "p", "modelID": "m"},
    )
    client.session_messages(cwd, "ses_1")
    client.session_children(cwd, "ses_1")
    client.session_todo(cwd, "ses_1")
    client.session_diff(cwd, "ses_1")
    client.file_status(cwd)
    client.session_abort(cwd, "ses_1")

    assert seen[0][0:3] == ("GET", "/global/health", "")
    session_create = seen[1]
    assert session_create[0:3] == ("POST", "/session", "")
    assert session_create[3][DIRECTORY_HEADER] == encoded
    assert session_create[4] == {"title": "eval-feia/run/cand-001"}
    prompt = seen[2]
    assert prompt[0:3] == ("POST", "/session/ses_1/message", "")
    assert prompt[3][DIRECTORY_HEADER] == encoded
    prompt_body = prompt[4]
    assert isinstance(prompt_body, dict)
    assert prompt_body == {
        "agent": "build",
        "model": {"providerID": "p", "modelID": "m"},
        "parts": [{"type": "text", "text": "hello"}],
    }
    assert "command" not in prompt_body
    assert "arguments" not in prompt_body
    for method, path, query, headers, _ in seen[3:7]:
        assert method == "GET"
        assert query == f"directory={encoded}"
        assert DIRECTORY_HEADER not in headers
        assert path in {
            "/session/ses_1/message",
            "/session/ses_1/children",
            "/session/ses_1/todo",
            "/session/ses_1/diff",
        }
    assert seen[7][0:3] == ("GET", "/file/status", f"directory={encoded}")
    assert seen[8][0:3] == ("POST", "/session/ses_1/abort", "")
    assert seen[8][3][DIRECTORY_HEADER] == encoded


def test_event_stream_uses_directory_query_and_sse_accept_header(tmp_path: Path) -> None:
    cwd = tmp_path / "candidate"
    encoded = encode_directory(cwd)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"type":"server.connected","properties":{}}\n\n',
        )

    client = OpencodeClient("http://opencode.test", transport=httpx.MockTransport(handler))

    with client.event_stream(cwd) as response:
        assert list(response.iter_lines()) == [
            'data: {"type":"server.connected","properties":{}}',
            "",
        ]

    request = seen[0]
    assert request.method == "GET"
    assert request.url.path == "/event"
    assert request.url.query.decode() == f"directory={encoded}"
    assert DIRECTORY_HEADER not in request.headers
    assert request.headers["accept"] == "text/event-stream"


def test_session_prompt_posts_command_request_shape(tmp_path: Path) -> None:
    cwd = tmp_path / "candidate"
    encoded = encode_directory(cwd)
    seen: list[tuple[str, str, str, dict[str, str], dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        json_body = None
        if request.content:
            json_body = json.loads(request.content.decode())
        seen.append(
            (
                request.method,
                request.url.path,
                request.url.query.decode(),
                dict(request.headers),
                json_body,
            )
        )
        if request.url.path == "/session/ses_1/command" and request.method == "POST":
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = OpencodeClient("http://opencode.test", transport=httpx.MockTransport(handler))
    client.session_prompt(
        cwd,
        "ses_1",
        "git status 확인해줘",
        command="/bash",
        agent="build",
        model={"providerID": "p", "modelID": "m"},
    )

    request = seen[0]
    assert request[0:3] == ("POST", "/session/ses_1/command", "")
    assert request[3][DIRECTORY_HEADER] == encoded
    request_body = request[4]
    assert isinstance(request_body, dict)
    assert request_body == {
        "agent": "build",
        "arguments": "git status 확인해줘",
        "command": "bash",
        "model": "p/m",
    }
    assert "parts" not in request_body
