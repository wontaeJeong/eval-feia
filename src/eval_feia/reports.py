from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .models import BatchOptions, RunResult, dataclass_to_json, now_iso


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
    path.write_text(json.dumps(dataclass_to_json(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def create_manifest(batch_id: str, options: BatchOptions, base_commit: str) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "created_at": now_iso(),
        "repo": str(options.repo.resolve()),
        "base_ref": options.branch,
        "base_commit": base_commit,
        "opencode_version": options.opencode_version,
        "parameters": {
            "count": options.count,
            "concurrency": options.concurrency,
            "prompt": options.prompt,
            "skill": options.skill,
            "provider": options.provider,
            "model": options.model,
            "base_port": options.base_port,
            "cwd_check": options.cwd_check,
            "restart_on_mismatch": options.restart_on_mismatch,
            "max_server_restarts": options.max_server_restarts,
        },
        "runs": [],
    }


def run_to_summary_row(result: RunResult, options: BatchOptions) -> dict[str, Any]:
    metrics = result.metrics
    validation = result.validation
    return {
        "batch_id": result.batch_id,
        "run_id": result.run_id,
        "status": result.status,
        "failure_class": result.failure_class,
        "model": options.model or "",
        "provider": options.provider or "",
        "opencode_version": options.opencode_version,
        "worktree_path": result.worktree.path if result.worktree else "",
        "port": result.server_info.port if result.server_info else "",
        "server_restart_count": metrics.server_restart_count,
        "total_messages": metrics.total_messages,
        "total_tool_calls": metrics.total_tool_calls,
        "total_subagent_run": metrics.total_subagent_run,
        "total_operational_ms": metrics.total_operational_ms,
        "validation_passed": validation.validation_passed if validation else False,
        "task_success": metrics.task_success,
        "error_message": result.error_message or "",
    }


def write_summary(batch_dir: Path, results: list[RunResult], options: BatchOptions) -> None:
    rows = [run_to_summary_row(result, options) for result in results]
    summary = {"batch_id": batch_dir.name, "created_at": now_iso(), "runs": rows}
    write_json(batch_dir / "summary.json", summary)
    with (batch_dir / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def collect_runs(batch_dir: Path, options: BatchOptions | None = None) -> list[dict[str, Any]]:
    run_dir = batch_dir / "runs"
    runs: list[dict[str, Any]] = []
    if not run_dir.exists():
        return runs
    for path in sorted(run_dir.glob("*/run.json")):
        runs.append(read_json(path))
    return runs
