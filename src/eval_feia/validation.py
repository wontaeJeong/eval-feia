from __future__ import annotations

import json
import re
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from .models import ValidationResult
from .reports import write_json


SECRET_PATTERNS = [
    re.compile(r"(?i)['\"]?(api[_-]?key|token|password|secret)['\"]?\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"(?i)bearer\s+[a-z0-9._\-]{16,}"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
]


def find_candidate_artifact(worktree: Path) -> Path | None:
    direct = [worktree / "team.json", worktree / "autogen_team.json", worktree / "autogen-team.json"]
    for path in direct:
        if path.exists() and path.is_file():
            return path
    matches = sorted(path for path in worktree.rglob("*team*.json") if ".git" not in path.parts and path.is_file())
    return matches[0] if matches else None


def validate_worktree(worktree: Path, output_path: Path | None = None) -> ValidationResult:
    result = ValidationResult()
    artifact = find_candidate_artifact(worktree)
    if artifact is None:
        result.errors.append("No AutoGen team JSON artifact found")
        _write_optional(output_path, result)
        return result
    result.artifact_found = True
    result.artifact_path = str(artifact.relative_to(worktree))
    text = artifact.read_text(encoding="utf-8")
    result.secret_scan_ok = not _contains_secret(text)
    if not result.secret_scan_ok:
        result.errors.append("Artifact contains a hardcoded secret-like value")
    try:
        data = json.loads(text)
        result.json_parse_ok = True
    except json.JSONDecodeError as exc:
        result.errors.append(f"JSON parse failed: {exc}")
        _write_optional(output_path, result)
        return result
    result.schema_ok = _looks_like_autogen_team(data)
    if not result.schema_ok:
        result.errors.append("Artifact does not look like an AutoGen team/component config")
    result.task_requirements_ok = _meets_task_requirements(data)
    if not result.task_requirements_ok:
        result.errors.append("Artifact does not cover web search, Knox mail report, summary, and mail abstraction")
    result.autogen_load_ok = _try_autogen_load(data)
    result.validation_passed = all(
        [
            result.artifact_found,
            result.json_parse_ok,
            result.schema_ok,
            result.secret_scan_ok,
            result.task_requirements_ok,
        ]
    )
    _write_optional(output_path, result)
    return result


def _write_optional(output_path: Path | None, result: ValidationResult) -> None:
    if output_path is not None:
        write_json(output_path, result)


def _contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def _flatten_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False).lower()


def _looks_like_autogen_team(data: Any) -> bool:
    text = _flatten_text(data)
    has_component = any(word in text for word in ("component", "provider", "component_type"))
    has_agents = any(word in text for word in ("participants", "agents", "assistantagent"))
    has_model = any(word in text for word in ("model_client", "modelclient", "model", "providerid"))
    has_termination = "termination" in text or "maxmessage" in text or "max_messages" in text
    return has_component and has_agents and has_model and has_termination


def _meets_task_requirements(data: Any) -> bool:
    text = _flatten_text(data)
    checks = [
        any(word in text for word in ("web", "search", "browser")),
        "knox" in text,
        "mail" in text or "email" in text,
        "report" in text,
        any(word in text for word in ("summar", "요약")),
    ]
    return all(checks)


def _try_autogen_load(data: Any) -> bool | None:
    if find_spec("autogen_core") is None:
        return None
    return bool(data)
