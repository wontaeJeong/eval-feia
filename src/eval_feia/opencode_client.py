from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


DIRECTORY_HEADER = "x-opencode-directory"


def normalize_command(command: str | None) -> str | None:
    if command is None:
        return None
    normalized = command.strip().lstrip("/").strip()
    return normalized or None


def build_opencode_prompt_request(
    session_id: str,
    prompt: str,
    *,
    command: str | None = None,
    agent: str | None = None,
    model: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    normalized_command = normalize_command(command)
    if normalized_command is None:
        body: dict[str, Any] = {"parts": [{"type": "text", "text": prompt}]}
        endpoint = "message"
    else:
        body = {"command": normalized_command, "arguments": prompt}
        endpoint = "command"

    if agent is not None:
        body["agent"] = agent
    if model is not None:
        body["model"] = _command_model(model) if normalized_command is not None else model

    return f"/session/{session_id}/{endpoint}", body


def _command_model(model: dict[str, Any]) -> str:
    return f"{model['providerID']}/{model['modelID']}"


def encode_directory(cwd: str | Path) -> str:
    path = Path(cwd).expanduser().resolve(strict=False)
    value = str(path)
    if "\\" in value and path.drive:
        value = value.replace("\\", "/")
    return quote(value, safe="")


class OpencodeClient:
    def __init__(
        self,
        base_url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        auth = None
        if password is not None:
            auth = httpx.BasicAuth(username or "opencode", password)
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            auth=auth,
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/global/health")

    def path(self, cwd: str | Path) -> dict[str, Any]:
        return self._request("GET", "/path", cwd=cwd)

    def project_current(self, cwd: str | Path) -> dict[str, Any]:
        return self._request("GET", "/project/current", cwd=cwd)

    def config(self, cwd: str | Path) -> dict[str, Any]:
        return self._request("GET", "/config", cwd=cwd)

    def vcs(self, cwd: str | Path) -> dict[str, Any]:
        return self._request("GET", "/vcs", cwd=cwd)

    def session_create(self, cwd: str | Path, title: str) -> dict[str, Any]:
        return self._request("POST", "/session", cwd=cwd, json={"title": title})

    def session_get(self, cwd: str | Path, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/session/{session_id}", cwd=cwd)

    def session_status(self, cwd: str | Path) -> dict[str, Any]:
        return self._request("GET", "/session/status", cwd=cwd)

    def session_prompt(
        self,
        cwd: str | Path,
        session_id: str,
        prompt: str,
        *,
        command: str | None = None,
        agent: str | None = None,
        model: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        path, body = build_opencode_prompt_request(
            session_id,
            prompt,
            command=command,
            agent=agent,
            model=model,
        )
        return self._request("POST", path, cwd=cwd, json=body, timeout=timeout)

    def session_abort(self, cwd: str | Path, session_id: str) -> dict[str, Any]:
        return self._request("POST", f"/session/{session_id}/abort", cwd=cwd)

    def session_messages(self, cwd: str | Path, session_id: str) -> Any:
        return self._request("GET", f"/session/{session_id}/message", cwd=cwd)

    def session_children(self, cwd: str | Path, session_id: str) -> Any:
        return self._request("GET", f"/session/{session_id}/children", cwd=cwd)

    def session_todo(self, cwd: str | Path, session_id: str) -> Any:
        return self._request("GET", f"/session/{session_id}/todo", cwd=cwd)

    def session_diff(self, cwd: str | Path, session_id: str) -> Any:
        return self._request("GET", f"/session/{session_id}/diff", cwd=cwd)

    def file_status(self, cwd: str | Path) -> Any:
        return self._request("GET", "/file/status", cwd=cwd)

    def _request(
        self,
        method: str,
        path: str,
        *,
        cwd: str | Path | None = None,
        json: Any | None = None,
        timeout: float | None = None,
    ) -> Any:
        headers: dict[str, str] = {}
        url = path
        if cwd is not None:
            encoded = encode_directory(cwd)
            if method.upper() in {"GET", "HEAD"}:
                separator = "&" if "?" in url else "?"
                url = f"{url}{separator}directory={encoded}"
            else:
                headers[DIRECTORY_HEADER] = encoded

        response = self._client.request(method, url, headers=headers, json=json, timeout=timeout)
        response.raise_for_status()
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"text": response.text}
