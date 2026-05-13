from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import httpx


class OpenCodeClientError(RuntimeError):
    pass


class OpenCodeConnectionError(OpenCodeClientError):
    pass


class OpenCodeUnexpectedResponse(OpenCodeClientError):
    pass


def extract_cwd_value(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("cwd", "path", "root", "directory"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    project = payload.get("project")
    if isinstance(project, dict):
        for key in ("path", "root", "directory"):
            value = project.get(key)
            if isinstance(value, str) and value:
                return value
    return None


class OpenCodeClient:
    def __init__(
        self,
        base_url: str,
        *,
        username: str = "opencode",
        password: str | None = None,
        timeout: float = 5.0,
        directory: Path | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.directory = directory
        self._auth = httpx.BasicAuth(username, password) if password else None

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.directory is not None:
            headers["x-opencode-directory"] = str(self.directory)
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            with httpx.Client(auth=self._auth, timeout=self.timeout, headers=self._headers()) as client:
                response = client.request(method, self._url(path), **kwargs)
        except httpx.HTTPError as exc:
            raise OpenCodeConnectionError(str(exc)) from exc
        if response.status_code == 401:
            raise OpenCodeUnexpectedResponse("OpenCode auth failed")
        if response.status_code >= 400:
            raise OpenCodeUnexpectedResponse(f"OpenCode returned HTTP {response.status_code} for {path}")
        return response

    def get_health(self) -> dict[str, Any]:
        return self._request("GET", "/global/health").json()

    def get_path(self) -> dict[str, Any]:
        return self._request("GET", "/path").json()

    def get_project_current(self) -> dict[str, Any]:
        return self._request("GET", "/project/current").json()

    def create_session(self, title: str, parent_id: str | None = None) -> dict[str, Any]:
        body = {"parentID": parent_id, "title": title}
        return self._request("POST", "/session", json=body).json()

    def send_prompt_async(self, session_id: str, payload: dict[str, Any]) -> None:
        response = self._request("POST", f"/session/{session_id}/prompt_async", json=payload)
        if response.status_code not in (200, 202, 204):
            raise OpenCodeUnexpectedResponse(f"Unexpected prompt_async HTTP {response.status_code}")

    def send_message(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/session/{session_id}/message", json=payload).json()

    def get_session_status(self) -> dict[str, Any]:
        return self._request("GET", "/session/status").json()

    def get_session_children(self, session_id: str) -> list[dict[str, Any]]:
        data = self._request("GET", f"/session/{session_id}/children").json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            children = data.get("children")
            if isinstance(children, list):
                return children
        return []

    def get_session_todo(self, session_id: str) -> list[dict[str, Any]]:
        data = self._request("GET", f"/session/{session_id}/todo").json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            todos = data.get("todos") or data.get("items")
            if isinstance(todos, list):
                return todos
        return []

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        data = self._request("GET", f"/session/{session_id}/message").json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            messages = data.get("messages")
            if isinstance(messages, list):
                return messages
        return []

    def get_diff(self, session_id: str) -> Any:
        response = self._request("GET", f"/session/{session_id}/diff")
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            return response.json()
        return response.text

    @contextmanager
    def open_event_lines(self, endpoint: str = "/event") -> Iterator[Iterator[str]]:
        timeout = httpx.Timeout(connect=self.timeout, read=1.0, write=self.timeout, pool=self.timeout)
        try:
            with httpx.Client(auth=self._auth, timeout=timeout, headers=self._headers()) as client:
                with client.stream("GET", self._url(endpoint)) as response:
                    if response.status_code >= 400:
                        raise OpenCodeUnexpectedResponse(f"OpenCode returned HTTP {response.status_code} for {endpoint}")
                    yield response.iter_lines()
        except httpx.ReadTimeout:
            yield iter(())
        except httpx.HTTPError as exc:
            raise OpenCodeConnectionError(str(exc)) from exc


def build_prompt_payload(prompt: str, *, provider: str, model: str, agent: str) -> dict[str, Any]:
    return {
        "messageID": None,
        "model": {"providerID": provider, "modelID": model},
        "agent": agent,
        "noReply": False,
        "system": None,
        "tools": None,
        "parts": [{"type": "text", "text": prompt}],
    }
