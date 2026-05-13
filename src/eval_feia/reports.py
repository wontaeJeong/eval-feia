from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, TextIO

from .models import BatchManifest, RunRecord, to_jsonable


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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2) + "\n")


def append_jsonl(stream: TextIO, payload: dict[str, Any]) -> None:
    stream.write(json.dumps(to_jsonable(payload), ensure_ascii=False, separators=(",", ":")) + "\n")
    stream.flush()


class JSONLRenderer:
    def __init__(self, stream: TextIO):
        self.stream = stream

    def emit(self, payload: dict[str, Any]) -> None:
        append_jsonl(self.stream, payload)


def write_manifest(path: Path, manifest: BatchManifest) -> None:
    write_json(path, manifest)


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_run_record(run_dir: Path, record: RunRecord) -> None:
    write_json(run_dir / "run.json", record.as_dict())


def run_summary_row(record: RunRecord, provider: str, model: str, opencode_version: str) -> dict[str, Any]:
    metrics = record.metrics
    worktree_path = record.worktree.path if record.worktree else ""
    port = record.server_info.port if record.server_info else ""
    return {
        "batch_id": record.batch_id,
        "run_id": record.run_id,
        "status": str(record.status),
        "failure_class": str(record.failure_class),
        "model": model,
        "provider": provider,
        "opencode_version": opencode_version,
        "worktree_path": worktree_path,
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


def write_summary(batch_dir: Path, rows: Iterable[dict[str, Any]]) -> None:
    materialized = list(rows)
    write_json(batch_dir / "summary.json", {"runs": materialized})
    with (batch_dir / "summary.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(materialized)


def summary_row_from_payload(run: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    raw_metrics = run.get("metrics")
    raw_worktree = run.get("worktree")
    raw_server_info = run.get("server_info")
    raw_validation = run.get("validation")
    metrics: dict[str, Any] = raw_metrics if isinstance(raw_metrics, dict) else {}
    worktree: dict[str, Any] = raw_worktree if isinstance(raw_worktree, dict) else {}
    server_info: dict[str, Any] = raw_server_info if isinstance(raw_server_info, dict) else {}
    validation: dict[str, Any] = raw_validation if isinstance(raw_validation, dict) else {}
    return {
        "batch_id": run.get("batch_id", manifest.get("batch_id", "")),
        "run_id": run.get("run_id", ""),
        "status": run.get("status", ""),
        "failure_class": run.get("failure_class", ""),
        "model": run.get("model", ""),
        "provider": run.get("provider", ""),
        "opencode_version": manifest.get("opencode_version", ""),
        "worktree_path": worktree.get("path", ""),
        "port": server_info.get("port", ""),
        "server_restart_count": metrics.get("server_restart_count", 0),
        "total_messages": metrics.get("total_messages", 0),
        "total_tool_calls": metrics.get("total_tool_calls", 0),
        "total_subagent_run": metrics.get("total_subagent_run", 0),
        "total_operational_ms": metrics.get("total_operational_ms", 0),
        "validation_passed": validation.get("validation_passed", metrics.get("validation_passed", False)),
        "task_success": metrics.get("task_success", False),
        "error_message": run.get("error_message") or "",
    }


def collect_summaries(output_dir: Path) -> int:
    count = 0
    for batch_dir in sorted(output_dir.glob("batch-*")):
        manifest_path = batch_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = load_manifest(manifest_path)
        rows: list[dict[str, Any]] = []
        for run_json in sorted((batch_dir / "runs").glob("*/run.json")):
            rows.append(summary_row_from_payload(load_manifest(run_json), manifest))
        write_summary(batch_dir, rows)
        count += 1
    return count
