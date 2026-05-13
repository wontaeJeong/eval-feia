# pyright: reportMissingImports=false
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from .models import CwdCheck, HealthCheck


PATH_FIELDS = {"cwd", "path", "root", "directory", "worktree"}


def compare_version(requested: str, reported: str | None) -> str:
    if not reported or reported == "unknown":
        return "unknown"
    return "match" if requested == reported else "mismatch"


def _path_candidates(data: Any, parent_key: str | None = None) -> list[str]:
    candidates: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            lower = key.lower()
            if lower in PATH_FIELDS and isinstance(value, str):
                candidates.append(value)
            elif parent_key in {"project", "workspace"} and lower in PATH_FIELDS and isinstance(value, str):
                candidates.append(value)
            candidates.extend(_path_candidates(value, lower))
    elif isinstance(data, list):
        for item in data:
            candidates.extend(_path_candidates(item, parent_key))
    return candidates


def extract_cwd(data: Any) -> str | None:
    candidates = []
    for raw in _path_candidates(data):
        try:
            resolved = str(Path(raw).expanduser().resolve())
        except OSError:
            continue
        if resolved not in candidates:
            candidates.append(resolved)
    if len(candidates) == 1:
        return candidates[0]
    return None


class OpenCodeClient:
    def __init__(self, base_url: str, username: str, password: str, directory: Path | None = None, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.directory = directory
        self.client = httpx.Client(
            base_url=self.base_url,
            auth=(username, password),
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self.client.close()

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(extra or {})
        if self.directory is not None:
            params.setdefault("directory", str(self.directory))
        return params

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.client.get(path, params=self._params(params))
        response.raise_for_status()
        return response.json()

    def post_json(self, path: str, body: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> httpx.Response:
        response = self.client.post(path, params=self._params(params), json=body or {})
        response.raise_for_status()
        return response

    def health(self, requested_version: str) -> HealthCheck:
        start = time.monotonic()
        try:
            data = self.get_json("/global/health", params={})
            healthy = bool(data.get("healthy"))
            reported = str(data.get("version") or "unknown")
            version_check = compare_version(requested_version, reported)
            return HealthCheck(
                ok=healthy,
                healthy=healthy,
                requested_version=requested_version,
                reported_version=reported,
                version_check=version_check,
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as exc:
            return HealthCheck(
                ok=False,
                requested_version=requested_version,
                reported_version="unknown",
                version_check="unknown",
                elapsed_ms=int((time.monotonic() - start) * 1000),
                error=str(exc),
            )

    def wait_health(self, requested_version: str, timeout_seconds: float, interval_seconds: float) -> HealthCheck:
        deadline = time.monotonic() + timeout_seconds
        last = self.health(requested_version)
        while time.monotonic() < deadline:
            last = self.health(requested_version)
            if last.ok:
                return last
            time.sleep(interval_seconds)
        last.error = last.error or "health timeout"
        return last

    def verify_cwd(self, expected: Path) -> CwdCheck:
        expected_resolved = str(expected.resolve())
        errors: list[str] = []
        for source, path in (("path", "/path"), ("project", "/project/current")):
            try:
                actual = extract_cwd(self.get_json(path))
            except Exception as exc:
                errors.append(f"{path}: {exc}")
                actual = None
            if actual is None:
                continue
            if actual == expected_resolved:
                return CwdCheck(ok=True, expected_cwd=expected_resolved, actual_cwd=actual, cwd_check="ok", source=source)
            return CwdCheck(ok=False, expected_cwd=expected_resolved, actual_cwd=actual, cwd_check="mismatch", source=source)
        return CwdCheck(ok=False, expected_cwd=expected_resolved, cwd_check="unknown", error="; ".join(errors) or "no cwd candidate")

    def create_session(self, run_id: str, skill: str | None = None) -> str:
        body: dict[str, Any] = {"title": f"eval-feia {run_id}"}
        if skill:
            body["agent"] = skill
        response = self.post_json("/session", body)
        data = response.json()
        session_id = data.get("id") or data.get("sessionID") or data.get("session_id")
        if not session_id:
            raise RuntimeError("session response did not include an id")
        return str(session_id)

    def send_prompt_async(self, session_id: str, prompt: str, skill: str | None, provider: str | None, model: str | None) -> None:
        body: dict[str, Any] = {"parts": [{"type": "text", "text": prompt}]}
        if skill:
            body["agent"] = skill
        if provider and model:
            body["model"] = {"providerID": provider, "modelID": model}
        try:
            response = self.post_json(f"/session/{session_id}/prompt_async", body)
            if response.status_code == 204:
                return
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {404, 405}:
                raise
        self.post_json(f"/session/{session_id}/message", body)

    def status(self) -> dict[str, Any]:
        data = self.get_json("/session/status")
        return data if isinstance(data, dict) else {}

    def children(self, session_id: str) -> list[dict[str, Any]]:
        data = self.get_json(f"/session/{session_id}/children")
        return data if isinstance(data, list) else []

    def todo(self, session_id: str) -> list[dict[str, Any]]:
        data = self.get_json(f"/session/{session_id}/todo")
        return data if isinstance(data, list) else []

    def diff(self, session_id: str) -> str:
        try:
            response = self.client.get(f"/session/{session_id}/diff", params=self._params())
            response.raise_for_status()
            if response.headers.get("content-type", "").startswith("application/json"):
                import json

                return json.dumps(response.json(), ensure_ascii=False, indent=2)
            return response.text
        except Exception:
            return ""
