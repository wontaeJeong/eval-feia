from __future__ import annotations

from typing import Any

from .models import Metrics, ValidationResult


def update_metrics_from_event(metrics: Metrics, payload: dict[str, Any]) -> None:
    event_type = str(payload.get("type", ""))
    if "message" in event_type:
        metrics.total_messages += 1
        role = str(payload.get("properties", {}).get("role", "")) if isinstance(payload.get("properties"), dict) else ""
        if role == "user":
            metrics.user_message_count += 1
        if role == "assistant":
            metrics.assistant_message_count += 1
    if "tool" in event_type:
        metrics.total_tool_calls += 1
        if "error" in event_type or payload.get("error"):
            metrics.tool_call_failure_count += 1
        else:
            metrics.tool_call_success_count += 1
    if "session" in event_type and ("child" in event_type or "created" in event_type):
        metrics.total_subagent_run += 1


def update_metrics_from_todo(metrics: Metrics, todo: list[dict[str, Any]]) -> None:
    metrics.total_todo_items = max(metrics.total_todo_items, len(todo))
    metrics.todo_completed_count = max(
        metrics.todo_completed_count,
        sum(1 for item in todo if str(item.get("status", "")).lower() in {"completed", "done"}),
    )
    metrics.todo_failed_count = max(
        metrics.todo_failed_count,
        sum(1 for item in todo if str(item.get("status", "")).lower() in {"failed", "cancelled"}),
    )


def apply_validation(metrics: Metrics, validation: ValidationResult) -> None:
    metrics.task_success = validation.validation_passed
    if not validation.validation_passed:
        metrics.validation_failures += 1
