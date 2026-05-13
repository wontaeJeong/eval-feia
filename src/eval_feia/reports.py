from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .models import RunRecord, jsonable, utc_now_iso


SUMMARY_COLUMNS = [
    "batch_id",
    "run_id",
    "status",
    "failure_class",
    "model",
    "provider",
    "opencode_version",
    "worktree_path",
    "port",
    "server_restart_count",
    "total_messages",
    "total_tool_calls",
    "total_subagent_run",
    "total_operational_ms",
    "validation_passed",
    "task_success",
    "error_message",
]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(jsonable(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", buffering=1) as handle:
        handle.write(json.dumps(jsonable(data), ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()


def run_summary_row(record: RunRecord, *, provider: str | None, model: str | None, opencode_version: str, port: int) -> dict[str, Any]:
    metrics = record.metrics
    return {
        "batch_id": record.batch_id,
        "run_id": record.run_id,
        "status": record.status,
        "failure_class": record.failure_class,
        "model": model or "",
        "provider": provider or "",
        "opencode_version": opencode_version,
        "worktree_path": record.worktree.path,
        "port": port,
        "server_restart_count": metrics.server_restart_count,
        "total_messages": metrics.total_messages,
        "total_tool_calls": metrics.total_tool_calls,
        "total_subagent_run": metrics.total_subagent_run,
        "total_operational_ms": metrics.total_operational_ms,
        "validation_passed": metrics.validation_passed,
        "task_success": metrics.task_success,
        "error_message": record.error_message or "",
    }


def write_summary(batch_dir: Path, rows: list[dict[str, Any]]) -> None:
    summary = {"created_at": utc_now_iso(), "run_count": len(rows), "runs": rows}
    write_json(batch_dir / "summary.json", summary)
    csv_path = batch_dir / "summary.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in SUMMARY_COLUMNS})


def load_run_records(batch_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for run_json in sorted((batch_dir / "runs").glob("*/run.json")):
        records.append(json.loads(run_json.read_text(encoding="utf-8")))
    return records
