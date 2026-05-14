from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

import httpx

from eval_feia.opencode_client import DIRECTORY_HEADER, OpencodeClient, encode_directory


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
    assert prompt[4] == {
        "agent": "build",
        "model": {"providerID": "p", "modelID": "m"},
        "parts": [{"type": "text", "text": "hello"}],
    }
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
