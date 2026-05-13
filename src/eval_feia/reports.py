from __future__ import annotations

import csv
import json
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

from .models import RunRecord, json_safe


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class JsonlWriter:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8")
        self._lock = Lock()

    def write(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._file.write(json.dumps(json_safe(event), ensure_ascii=False) + "\n")
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            self._file.close()

    def __enter__(self) -> "JsonlWriter":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


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


def run_summary_row(record: RunRecord, provider: str, model: str, version: str) -> dict[str, Any]:
    return {
        "batch_id": record.batch_id,
        "run_id": record.run_id,
        "status": record.status,
        "failure_class": record.failure_class,
        "model": model,
        "provider": provider,
        "opencode_version": version,
        "worktree_path": str(record.worktree.path) if record.worktree else "",
        "port": record.server_info.port if record.server_info else "",
        "server_restart_count": record.metrics.server_restart_count,
        "total_messages": record.metrics.total_messages,
        "total_tool_calls": record.metrics.total_tool_calls,
        "total_subagent_run": record.metrics.total_subagent_run,
        "total_operational_ms": record.metrics.total_operational_ms,
        "validation_passed": record.validation.validation_passed,
        "task_success": record.metrics.task_success,
        "error_message": record.error_message or "",
    }


def write_summary(batch_dir: Path, records: Iterable[RunRecord], provider: str, model: str, version: str) -> None:
    rows = [run_summary_row(record, provider, model, version) for record in records]
    summary = {
        "batch_dir": str(batch_dir),
        "total_runs": len(rows),
        "completed": sum(1 for row in rows if row["status"] == "completed"),
        "failed": sum(1 for row in rows if row["status"] != "completed"),
        "runs": rows,
    }
    write_json(batch_dir / "summary.json", summary)
    csv_path = batch_dir / "summary.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def collect_existing_batch(batch_dir: Path) -> list[dict[str, Any]]:
    run_json_paths = sorted((batch_dir / "runs").glob("*/run.json"))
    return [read_json(path) for path in run_json_paths]
