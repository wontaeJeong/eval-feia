from __future__ import annotations

from typing import Any

from .models import Metrics, ValidationResult


def update_metrics_from_event(metrics: Metrics, event: dict[str, Any]) -> None:
    event_type = str(event.get("type", event.get("event", ""))).lower()
    if "message" in event_type:
        metrics.total_messages += 1
        role = str(event.get("role", event.get("properties", {}).get("role", ""))).lower() if isinstance(event.get("properties", {}), dict) else ""
        if role == "user":
            metrics.user_message_count += 1
        elif role == "assistant":
            metrics.assistant_message_count += 1
    if "tool" in event_type:
        metrics.total_tool_calls += 1
        status = str(event.get("status", event.get("properties", {}).get("status", ""))).lower() if isinstance(event.get("properties", {}), dict) else ""
        if status in {"success", "completed", "ok"}:
            metrics.tool_call_success_count += 1
        elif status in {"failed", "error"}:
            metrics.tool_call_failure_count += 1
    if "subagent" in event_type or "child" in event_type:
        metrics.total_subagent_run += 1


def update_metrics_from_snapshots(metrics: Metrics, children: Any, todo: Any) -> None:
    if isinstance(children, list):
        metrics.total_subagent_run = max(metrics.total_subagent_run, len(children))
        metrics.max_session_depth = max(metrics.max_session_depth, 1 if children else 0)
    if isinstance(todo, list):
        metrics.total_todo_items = max(metrics.total_todo_items, len(todo))
        completed = 0
        failed = 0
        for item in todo:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", item.get("state", ""))).lower()
            if status in {"done", "completed", "complete"}:
                completed += 1
            if status in {"failed", "error"}:
                failed += 1
        metrics.todo_completed_count = max(metrics.todo_completed_count, completed)
        metrics.todo_failed_count = max(metrics.todo_failed_count, failed)


def apply_validation_metrics(metrics: Metrics, validation: ValidationResult) -> None:
    metrics.artifact_found = validation.artifact_found
    metrics.json_parse_ok = validation.json_parse_ok
    metrics.autogen_load_ok = validation.autogen_load_ok
    metrics.validation_passed = validation.validation_passed
    metrics.task_success = validation.validation_passed
    metrics.validation_failures = 0 if validation.validation_passed else 1
