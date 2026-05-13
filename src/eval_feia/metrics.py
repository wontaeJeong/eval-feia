from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Metrics


def metrics_from_events(events_path: Path) -> Metrics:
    metrics = Metrics()
    if not events_path.exists():
        return metrics
    for line in events_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        classify_event(metrics, event)
    return metrics


def classify_event(metrics: Metrics, event: dict[str, Any]) -> None:
    event_type = str(event.get("type") or event.get("event") or "").lower()
    if "message" in event_type:
        metrics.total_messages += 1
        role = str(event.get("role") or event.get("message", {}).get("role") or "").lower()
        if role == "user":
            metrics.user_message_count += 1
        if role == "assistant":
            metrics.assistant_message_count += 1
    if "tool" in event_type:
        metrics.total_tool_calls += 1
        if any(token in event_type for token in ("success", "completed", "done")):
            metrics.tool_call_success_count += 1
        if any(token in event_type for token in ("fail", "error")):
            metrics.tool_call_failure_count += 1
    if "subagent" in event_type or "child" in event_type:
        metrics.total_subagent_run += 1
    if "restart" in event_type:
        metrics.server_restart_count += 1
    if "validation" in event_type and event.get("passed") is False:
        metrics.validation_failures += 1


def merge_validation_metrics(metrics: Metrics, validation: Any) -> Metrics:
    metrics.artifact_found = bool(validation.artifact_found)
    metrics.json_parse_ok = bool(validation.json_parse_ok)
    metrics.autogen_load_ok = validation.autogen_load_ok
    metrics.validation_passed = bool(validation.validation_passed)
    metrics.task_success = bool(validation.validation_passed)
    if not validation.validation_passed:
        metrics.validation_failures += 1
    return metrics
