from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import ValidationResult
from .reports import write_json


CANDIDATE_NAMES = ["team.json", "autogen_team.json", "autogen-team.json"]
SECRET_KEY_RE = re.compile(r"(api[_-]?key|secret|token|password|credential|authorization)", re.I)
SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|Bearer\s+[A-Za-z0-9._-]{16,}|[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,})"
)
PLACEHOLDER_RE = re.compile(r"(your-|example|placeholder|\$\{|<.*>|\.\.\.)", re.I)


def find_autogen_config(root: Path) -> Path | None:
    for name in CANDIDATE_NAMES:
        candidate = root / name
        if candidate.exists():
            return candidate
    matches = sorted(root.rglob("*team*.json"))
    return matches[0] if matches else None


def validate_artifacts(root: Path, write_to: Path | None = None) -> ValidationResult:
    result = ValidationResult()
    artifact = find_autogen_config(root)
    if artifact is None:
        result.errors.append("AutoGen team config artifact not found")
        if write_to:
            write_json(write_to, result)
        return result
    result.artifact_found = True
    result.artifact_path = str(artifact)
    try:
        data = json.loads(artifact.read_text())
        result.json_parse_ok = True
    except json.JSONDecodeError as exc:
        result.errors.append(f"invalid JSON: {exc}")
        if write_to:
            write_json(write_to, result)
        return result
    schema_errors = validate_team_shape(data)
    result.schema_ok = not schema_errors
    result.errors.extend(schema_errors)
    secret_errors = scan_for_secrets(data)
    result.secret_scan_ok = not secret_errors
    result.errors.extend(secret_errors)
    task_errors = validate_task_requirements(data)
    result.task_requirements_ok = not task_errors
    result.errors.extend(task_errors)
    result.autogen_load_ok = None
    result.validation_passed = all(
        [result.artifact_found, result.json_parse_ok, result.schema_ok, result.secret_scan_ok, result.task_requirements_ok]
    )
    if write_to:
        write_json(write_to, result)
    return result


def validate_team_shape(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["top-level config must be an object"]
    if not isinstance(data.get("provider"), str) or not data["provider"]:
        errors.append("missing provider")
    if data.get("component_type") != "team":
        errors.append("component_type must be team")
    config = data.get("config")
    if not isinstance(config, dict):
        return errors + ["missing config object"]
    participants = config.get("participants") or config.get("agents")
    if not isinstance(participants, list) or not participants:
        errors.append("missing participants or agents")
    elif not any(_has_model_client(participant) for participant in participants if isinstance(participant, dict)):
        errors.append("missing model client config")
    if not isinstance(config.get("termination_condition"), dict):
        errors.append("missing termination condition")
    return errors


def _has_model_client(participant: dict[str, Any]) -> bool:
    config = participant.get("config")
    if not isinstance(config, dict):
        return False
    model_client = config.get("model_client") or config.get("modelClient")
    return isinstance(model_client, dict) and isinstance(model_client.get("config"), dict)


def validate_task_requirements(data: Any) -> list[str]:
    text = json.dumps(data, ensure_ascii=False).lower()
    requirements = {
        "web search": ["web", "search", "검색"],
        "Knox mail": ["knox", "mail", "메일"],
        "summary/report": ["summary", "summar", "report", "리포트", "보고"],
    }
    missing = [name for name, tokens in requirements.items() if not any(token in text for token in tokens)]
    return [f"missing task requirement: {name}" for name in missing]


def scan_for_secrets(data: Any) -> list[str]:
    errors: list[str] = []

    def walk(value: Any, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child_path = f"{path}.{key}"
                if SECRET_KEY_RE.search(str(key)) and isinstance(item, str) and _looks_secret(item):
                    errors.append(f"hardcoded secret at {child_path}")
                walk(item, child_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, str) and _looks_secret(value):
            errors.append(f"hardcoded secret at {path}")

    walk(data)
    return sorted(set(errors))


def _looks_secret(value: str) -> bool:
    if PLACEHOLDER_RE.search(value):
        return False
    return bool(SECRET_VALUE_RE.search(value))
