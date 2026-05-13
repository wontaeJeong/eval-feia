from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable

import httpx

from .models import CwdCheckResult, CwdCheckStatus, ServerHealth, VersionCheck
from .sse import SSEEvent, iter_sse_events


class OpenCodeClientError(RuntimeError):
    pass


class OpenCodeClient:
    def __init__(
        self,
        base_url: str,
        password: str,
        username: str = "opencode",
        timeout: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.password = password
        self.username = username
        self._owns_client = client is None
        self.stream_timeout = httpx.Timeout(timeout, connect=timeout, read=None, write=timeout, pool=timeout)
        self.client = client or httpx.Client(
            base_url=self.base_url,
            auth=httpx.BasicAuth(username, password),
            timeout=httpx.Timeout(timeout, connect=timeout, read=timeout, write=timeout, pool=timeout),
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "OpenCodeClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def health(self) -> ServerHealth:
        started = time.monotonic()
        response = self.client.get("/global/health")
        response.raise_for_status()
        payload = response.json()
        return ServerHealth(
            healthy=bool(payload.get("healthy")),
            reported_version=payload.get("version"),
            elapsed_ms=int((time.monotonic() - started) * 1000),
            raw=payload,
        )

    def poll_health(self, timeout_seconds: float, interval_seconds: float) -> ServerHealth:
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() <= deadline:
            try:
                health = self.health()
                if time.monotonic() > deadline:
                    break
                if health.healthy:
                    return health
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
            time.sleep(interval_seconds)
        raise OpenCodeClientError(f"health timeout: {last_error}")

    def path(self) -> dict[str, Any]:
        response = self.client.get("/path")
        response.raise_for_status()
        return response.json()

    def project_current(self) -> dict[str, Any]:
        response = self.client.get("/project/current")
        response.raise_for_status()
        return response.json()

    def check_cwd(self, expected_cwd: Path) -> CwdCheckResult:
        expected = str(expected_cwd.resolve())
        raw: dict[str, Any] = {}
        source: str | None = None
        actual: str | None = None
        try:
            raw = self.path()
            actual = extract_path(raw, ["cwd", "path", "root", "directory"])
            source = "/path"
        except httpx.HTTPError:
            raw = {}
        if not actual:
            try:
                raw = self.project_current()
                actual = extract_path(raw, ["project.path", "project.root", "project.directory", "path", "root"])
                source = "/project/current"
            except httpx.HTTPError:
                raw = {}
        if not actual:
            return CwdCheckResult(expected_cwd=expected, actual_cwd=None, status=CwdCheckStatus.UNKNOWN, source=source, raw=raw)
        actual_resolved = str(Path(actual).resolve())
        status = CwdCheckStatus.OK if actual_resolved == expected else CwdCheckStatus.MISMATCH
        return CwdCheckResult(expected_cwd=expected, actual_cwd=actual_resolved, status=status, source=source, raw=raw)

    def create_session(self, title: str, parent_id: str | None = None) -> str:
        response = self.client.post("/session", json={"parentID": parent_id, "title": title})
        response.raise_for_status()
        payload = response.json() if response.content else {}
        session_id = payload.get("id") or payload.get("sessionID") or payload.get("session", {}).get("id")
        if not session_id:
            raise OpenCodeClientError("session response did not include id")
        return str(session_id)

    def send_prompt_async(self, session_id: str, prompt: str, provider: str, model: str, agent: str) -> None:
        payload = {
            "messageID": None,
            "model": {"providerID": provider, "modelID": model},
            "agent": agent,
            "noReply": False,
            "system": None,
            "tools": None,
            "parts": [{"type": "text", "text": prompt}],
        }
        response = self.client.post(f"/session/{session_id}/prompt_async", json=payload)
        response.raise_for_status()

    def session_status(self) -> Any:
        response = self.client.get("/session/status")
        response.raise_for_status()
        return response.json()

    def children(self, session_id: str) -> Any:
        response = self.client.get(f"/session/{session_id}/children")
        response.raise_for_status()
        return response.json()

    def todo(self, session_id: str) -> Any:
        response = self.client.get(f"/session/{session_id}/todo")
        response.raise_for_status()
        return response.json()

    def diff(self, session_id: str) -> str:
        response = self.client.get(f"/session/{session_id}/diff")
        response.raise_for_status()
        return response.text

    def messages(self, session_id: str) -> Any:
        response = self.client.get(f"/session/{session_id}/message")
        response.raise_for_status()
        return response.json()

    def stream_sse(self, endpoint: str = "/event", on_connected: Callable[[], None] | None = None) -> Iterator[SSEEvent]:
        with self.client.stream("GET", endpoint, timeout=self.stream_timeout) as response:
            response.raise_for_status()
            if on_connected is not None:
                on_connected()
            yield from iter_sse_events(response.iter_lines())


def compare_version(requested: str, reported: str | None) -> VersionCheck:
    if not reported:
        return VersionCheck.UNKNOWN
    return VersionCheck.MATCH if requested == reported else VersionCheck.MISMATCH


def extract_path(payload: dict[str, Any], candidates: list[str]) -> str | None:
    for candidate in candidates:
        current: Any = payload
        for part in candidate.split("."):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        if isinstance(current, str) and current:
            return current
    return None
