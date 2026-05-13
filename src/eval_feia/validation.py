from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

from .models import ValidationResult


SECRET_PATTERNS = [
    re.compile(r"(?i)['\"]?(api[_-]?key|secret|password|token)['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-.]{16,}"),
    re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"),
]


def find_artifact(worktree: Path) -> Path | None:
    candidates = [worktree / "team.json", worktree / "autogen_team.json", worktree / "autogen-team.json"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    matches = sorted(path for path in worktree.rglob("*team*.json") if path.is_file())
    return matches[0] if matches else None


def _walk_values(value: Any) -> list[Any]:
    values = [value]
    if isinstance(value, dict):
        for item in value.values():
            values.extend(_walk_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_walk_values(item))
    return values


def _contains_key(data: Any, names: set[str]) -> bool:
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in names:
                return True
            if _contains_key(value, names):
                return True
    elif isinstance(data, list):
        return any(_contains_key(item, names) for item in data)
    return False


def schema_ok(data: Any) -> bool:
    text = json.dumps(data, ensure_ascii=False).lower()
    has_component = _contains_key(data, {"provider", "component", "component_provider_override", "type"})
    has_agents = _contains_key(data, {"participants", "agents", "team"})
    has_model = "model" in text or "model_client" in text or "modelclient" in text
    has_termination = "termination" in text or "maxmessage" in text or "stop" in text
    return has_component and has_agents and has_model and has_termination


def task_requirements_ok(data: Any) -> bool:
    text = json.dumps(data, ensure_ascii=False).lower()
    search_ok = "search" in text or "web" in text or "browser" in text
    mail_ok = "mail" in text or "email" in text or "knox" in text
    report_ok = "report" in text or "summary" in text or "summar" in text
    return search_ok and mail_ok and report_ok


def scan_secrets(text: str) -> list[str]:
    return [pattern.pattern for pattern in SECRET_PATTERNS if pattern.search(text)]


def try_autogen_load(data: Any) -> bool | None:
    if importlib.util.find_spec("autogen_agentchat") is None and importlib.util.find_spec("autogen_core") is None:
        return None
    try:
        from autogen_core import ComponentModel  # type: ignore[import-not-found]

        ComponentModel.model_validate(data)
        return True
    except Exception:
        return False


def validate_worktree(worktree: Path) -> ValidationResult:
    errors: list[str] = []
    artifact = find_artifact(worktree)
    if artifact is None:
        return ValidationResult(
            artifact_found=False,
            artifact_path=None,
            json_parse_ok=False,
            schema_ok=False,
            autogen_load_ok=None,
            secret_scan_ok=True,
            task_requirements_ok=False,
            validation_passed=False,
            errors=["no AutoGen team JSON artifact found"],
        )
    raw = artifact.read_text(encoding="utf-8")
    secret_errors = scan_secrets(raw)
    secret_ok = not secret_errors
    if secret_errors:
        errors.append("hardcoded secret pattern found")
    data: Any = None
    json_ok = False
    try:
        data = json.loads(raw)
        json_ok = True
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON: {exc}")
    shape_ok = schema_ok(data) if json_ok else False
    if json_ok and not shape_ok:
        errors.append("missing AutoGen team/component shape")
    task_ok = task_requirements_ok(data) if json_ok else False
    if json_ok and not task_ok:
        errors.append("missing task-specific web/Knox mail report behavior")
    autogen_load_ok = try_autogen_load(data) if json_ok else None
    if autogen_load_ok is False:
        errors.append("AutoGen component config load failed")
    passed = bool(artifact and json_ok and shape_ok and secret_ok and task_ok)
    return ValidationResult(
        artifact_found=True,
        artifact_path=str(artifact.relative_to(worktree)),
        json_parse_ok=json_ok,
        schema_ok=shape_ok,
        autogen_load_ok=autogen_load_ok,
        secret_scan_ok=secret_ok,
        task_requirements_ok=task_ok,
        validation_passed=passed,
        errors=errors,
    )
