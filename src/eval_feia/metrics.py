from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .live import LiveState
from .models import Metrics, ValidationResult


def compute_metrics(
    *,
    run_dir: Path,
    state: LiveState,
    validation: ValidationResult,
    restart_count: int,
    server_start_elapsed_ms: int,
    total_operational_ms: int,
    idle_quiet_ms: int,
    prompt_sent: bool,
    completed: bool,
    timeout: bool,
    harness_error: bool,
) -> Metrics:
    events = _read_jsonl(run_dir / "events.jsonl")
    todos = _read_jsonl(run_dir / "todo_snapshots.jsonl")
    metrics = Metrics()
    metrics.total_messages = state.message_count or sum(1 for event in events if "message" in str(event.get("event", event.get("type", ""))).lower())
    metrics.total_tool_calls = state.tool_call_count or sum(1 for event in events if "tool" in str(event.get("event", event.get("type", ""))).lower())
    metrics.tool_call_success_count = sum(1 for event in events if "tool" in str(event).lower() and "completed" in str(event).lower())
    metrics.tool_call_failure_count = sum(1 for event in events if "tool" in str(event).lower() and "fail" in str(event).lower())
    metrics.total_subagent_run = state.child_session_count
    metrics.max_session_depth = 1 + (1 if state.child_session_count else 0)
    flattened_todos = _flatten_todos(todos)
    metrics.total_todo_items = len(flattened_todos)
    metrics.todo_completed_count = sum(1 for item in flattened_todos if str(item.get("status", "")).lower() in {"completed", "done"})
    metrics.todo_failed_count = sum(1 for item in flattened_todos if str(item.get("status", "")).lower() in {"failed", "cancelled", "error"})
    metrics.total_operational_ms = total_operational_ms
    metrics.server_start_elapsed_ms = server_start_elapsed_ms
    metrics.idle_quiet_ms = idle_quiet_ms
    metrics.validation_failures = 0 if validation.validation_passed else 1
    metrics.server_restart_count = restart_count
    metrics.server_ready = server_start_elapsed_ms >= 0
    metrics.prompt_sent = prompt_sent
    metrics.opencode_completed = completed
    metrics.timeout = timeout
    metrics.harness_error = harness_error
    metrics.artifact_found = validation.artifact_found
    metrics.json_parse_ok = validation.json_parse_ok
    metrics.autogen_load_ok = validation.autogen_load_ok
    metrics.validation_passed = validation.validation_passed
    metrics.task_success = completed and validation.validation_passed
    return metrics


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def _flatten_todos(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: list[dict[str, Any]] = []
    for snapshot in snapshots:
        items = snapshot.get("items") or snapshot.get("todos")
        if isinstance(items, list):
            latest = [item for item in items if isinstance(item, dict)]
    return latest
