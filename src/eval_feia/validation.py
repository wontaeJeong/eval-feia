from __future__ import annotations

import json
import importlib.util
import importlib
import re
from pathlib import Path
from typing import Any

from .models import ValidationResult


SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_]*(api[_-]?key|token|password|secret)[A-Za-z0-9_]*\b\s*[:=]\s*[\"'][^\"']{12,}[\"']", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
]


def find_artifact(root: Path) -> Path | None:
    for name in ("team.json", "autogen_team.json", "autogen-team.json"):
        candidate = root / name
        if candidate.exists():
            return candidate
    matches = sorted(path for path in root.rglob("*team*.json") if path.is_file())
    return matches[0] if matches else None


def secret_scan(text: str) -> list[str]:
    return [pattern.pattern for pattern in SECRET_PATTERNS if pattern.search(text)]


def _contains_key(value: Any, names: set[str]) -> bool:
    if isinstance(value, dict):
        if any(str(key).lower() in names for key in value):
            return True
        return any(_contains_key(item, names) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, names) for item in value)
    return False


def shape_ok(config: Any) -> bool:
    has_component = _contains_key(config, {"provider", "component_type", "componenttype", "type", "component"})
    has_agents = _contains_key(config, {"participants", "agents", "agent", "members"})
    has_model = _contains_key(config, {"model_client", "modelclient", "model", "model_client_config"})
    has_termination = _contains_key(config, {"termination_condition", "termination", "stop_condition"})
    return has_component and has_agents and has_model and has_termination


def task_requirements_ok(config: Any) -> bool:
    text = json.dumps(config, ensure_ascii=False).lower()
    requirements = [
        ("knox",),
        ("mail", "email"),
        ("web", "search", "browser"),
        ("report", "summary", "summar"),
    ]
    return all(any(term in text for term in group) for group in requirements)


def try_autogen_load(config: Any) -> tuple[bool | None, str | None]:
    if importlib.util.find_spec("autogen_core") is None and importlib.util.find_spec("autogen_agentchat") is None:
        return None, None
    errors: list[str] = []
    try:
        core = importlib.import_module("autogen_core")
        component_model = getattr(core, "ComponentModel")
        loader = getattr(core, "ComponentLoader")
        model = component_model.model_validate(config) if hasattr(component_model, "model_validate") else component_model(**config)
        loader.load_component(model)
        return True, None
    except Exception as exc:
        errors.append(str(exc))
    try:
        core = importlib.import_module("autogen_core")
        component = getattr(core, "Component")
        component.load_component(config)
        return True, None
    except Exception as exc:
        errors.append(str(exc))
    return False, "; ".join(error for error in errors if error) or "AutoGen load failed"


def validate_autogen_config(root: Path) -> ValidationResult:
    result = ValidationResult()
    artifact = find_artifact(root)
    if artifact is None:
        result.errors.append("No AutoGen team JSON artifact found")
        return result
    result.artifact_found = True
    result.artifact_path = str(artifact.relative_to(root))
    text = artifact.read_text(encoding="utf-8")
    secret_matches = secret_scan(text)
    result.secret_scan_ok = not secret_matches
    if secret_matches:
        result.errors.append("Artifact contains hardcoded secret-like values")
    try:
        config = json.loads(text)
    except json.JSONDecodeError as exc:
        result.errors.append(f"Artifact is not valid JSON: {exc}")
        return result
    result.json_parse_ok = True
    result.schema_ok = shape_ok(config)
    if not result.schema_ok:
        result.errors.append("Artifact does not look like an AutoGen Teams component config")
    result.task_requirements_ok = task_requirements_ok(config)
    if not result.task_requirements_ok:
        result.errors.append("Artifact does not cover web search, Knox mail, and report requirements")
    result.autogen_load_ok, load_error = try_autogen_load(config)
    if result.autogen_load_ok is False:
        result.errors.append(f"AutoGen load failed: {load_error}")
    result.validation_passed = bool(
        result.artifact_found
        and result.json_parse_ok
        and result.schema_ok
        and result.secret_scan_ok
        and result.task_requirements_ok
        and result.autogen_load_ok is not False
    )
    return result
