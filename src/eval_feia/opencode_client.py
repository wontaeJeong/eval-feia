from __future__ import annotations

import time
from contextlib import AbstractContextManager
from pathlib import Path
from types import TracebackType
from typing import Any, Iterator

import httpx

from .models import CwdCheck, HealthCheck
from .process import USERNAME
from .sse import SseEvent, SseParser


PATH_KEYS = {"cwd", "path", "root", "directory"}
PROJECT_KEYS = {"project"}


class OpenCodeClientError(RuntimeError):
    pass


def check_version(requested: str, reported: str | None) -> str:
    if not reported or reported == "unknown":
        return "unknown"
    return "match" if str(requested) == str(reported) else "mismatch"


def extract_path(value: Any) -> str | None:
    return _extract_path(value, allow_direct_string=True)


def _extract_path(value: Any, allow_direct_string: bool = False) -> str | None:
    if isinstance(value, str) and allow_direct_string:
        return value
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in PATH_KEYS and isinstance(item, str):
                return item
            if lowered in PROJECT_KEYS or isinstance(item, (dict, list)):
                found = _extract_path(item, allow_direct_string=False)
                if found:
                    return found
    if isinstance(value, list):
        for item in value:
            found = _extract_path(item, allow_direct_string=False)
            if found:
                return found
    return None


def extract_session_id(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("id", "sessionID", "session_id"):
            found = value.get(key)
            if found:
                return str(found)
        nested = value.get("session")
        if nested is not None:
            return extract_session_id(nested)
    raise OpenCodeClientError("session response did not include an id")


class SseConnection:
    def __init__(self, client: httpx.Client, endpoint: str, params: dict[str, str] | None = None) -> None:
        self.client = client
        self.endpoint = endpoint
        self.params = params or {}
        self._ctx: AbstractContextManager[httpx.Response] | None = None
        self._response: httpx.Response | None = None
        self.connected = False

    def __enter__(self) -> SseConnection:
        stream_timeout = httpx.Timeout(10.0, connect=10.0, read=None, write=10.0, pool=10.0)
        self._ctx = self.client.stream("GET", self.endpoint, params=self.params, headers={"Accept": "text/event-stream"}, timeout=stream_timeout)
        response = self._ctx.__enter__()
        response.raise_for_status()
        self._response = response
        self.connected = True
        return self

    def events(self, limit: int | None = None) -> Iterator[SseEvent]:
        if self._response is None:
            raise OpenCodeClientError("SSE connection is not open")
        parser = SseParser()
        emitted = 0
        for line in self._response.iter_lines():
            for event in parser.feed_line(line):
                yield event
                emitted += 1
                if limit is not None and emitted >= limit:
                    return
        for event in parser.finish():
            yield event

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> bool | None:
        self.connected = False
        if self._ctx is not None:
            return self._ctx.__exit__(exc_type, exc, tb)
        return None


class OpenCodeClient:
    def __init__(self, base_url: str, password: str, username: str = USERNAME, directory: Path | None = None, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.directory = directory
        self.client = httpx.Client(
            base_url=self.base_url,
            auth=(username, password),
            timeout=httpx.Timeout(timeout, connect=timeout, read=timeout, write=timeout, pool=timeout),
        )

    def close(self) -> None:
        self.client.close()

    def _params(self) -> dict[str, str]:
        return {"directory": str(self.directory)} if self.directory is not None else {}

    def get_json(self, path: str) -> Any:
        response = self.client.get(path, params=self._params())
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    def post_json(self, path: str, payload: dict[str, Any] | None = None) -> httpx.Response:
        response = self.client.post(path, params=self._params(), json=payload or {})
        response.raise_for_status()
        return response

    def health(self) -> dict[str, Any]:
        data = self.get_json("/global/health")
        return data if isinstance(data, dict) else {}

    def poll_health(self, timeout_seconds: float, interval_seconds: float) -> HealthCheck:
        started = time.monotonic()
        attempts = 0
        last_error: str | None = None
        version = "unknown"
        while time.monotonic() - started <= timeout_seconds:
            attempts += 1
            try:
                data = self.health()
                version = str(data.get("version") or "unknown")
                if data.get("healthy") is True:
                    return HealthCheck(ok=True, healthy=True, version=version, attempts=attempts, elapsed_ms=int((time.monotonic() - started) * 1000))
                last_error = "health response was not healthy"
            except Exception as exc:  # intentionally records transient startup errors
                last_error = str(exc)
            time.sleep(interval_seconds)
        return HealthCheck(ok=False, healthy=False, version=version, attempts=attempts, elapsed_ms=int((time.monotonic() - started) * 1000), error=last_error or "timeout")

    def verify_cwd(self, expected: Path) -> CwdCheck:
        expected_resolved = str(expected.resolve())
        for source, endpoint in (("/path", "/path"), ("/project/current", "/project/current")):
            try:
                data = self.get_json(endpoint)
            except httpx.HTTPError as exc:
                last_error = str(exc)
                continue
            found = extract_path(data)
            if not found:
                last_error = f"{source} response had no path"
                continue
            try:
                actual_resolved = str(Path(found).resolve())
            except OSError:
                actual_resolved = found
            result = "ok" if actual_resolved == expected_resolved else "mismatch"
            return CwdCheck(result=result, expected_cwd=expected_resolved, actual_cwd=actual_resolved, source=source)
        return CwdCheck(result="unknown", expected_cwd=expected_resolved, actual_cwd=None, source=None, error=locals().get("last_error", "no cwd endpoint data"))

    def create_session(self, title: str) -> str:
        response = self.post_json("/session", {"title": title})
        return extract_session_id(response.json())

    def prompt_payload(self, prompt: str, skill: str, provider: str | None = None, model: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"agent": skill, "parts": [{"type": "text", "text": prompt}]}
        if provider or model:
            payload["model"] = {"providerID": provider or "", "modelID": model or ""}
        return payload

    def send_prompt(self, session_id: str, prompt: str, skill: str, provider: str | None = None, model: str | None = None) -> str:
        payload = self.prompt_payload(prompt, skill, provider, model)
        try:
            response = self.client.post(f"/session/{session_id}/prompt_async", params=self._params(), json=payload)
            if response.status_code not in {404, 405}:
                response.raise_for_status()
                return "prompt_async"
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {404, 405}:
                raise
        self.post_json(f"/session/{session_id}/message", payload)
        return "message"

    def status(self) -> Any:
        return self.get_json("/session/status")

    def children(self, session_id: str) -> Any:
        return self.get_json(f"/session/{session_id}/children")

    def todo(self, session_id: str) -> Any:
        return self.get_json(f"/session/{session_id}/todo")

    def diff(self, session_id: str) -> str:
        response = self.client.get(f"/session/{session_id}/diff", params=self._params())
        response.raise_for_status()
        return response.text

    def messages(self, session_id: str) -> Any:
        return self.get_json(f"/session/{session_id}/message")

    def open_sse(self, endpoint: str = "/event") -> SseConnection:
        return SseConnection(self.client, endpoint, self._params())
