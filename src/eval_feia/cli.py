# pyright: reportMissingImports=false
from __future__ import annotations

import json
import sys
import csv
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .cleanup import cleanup_manifest
from .models import BatchOptions
from .orchestrator import run_batch
from .reports import SUMMARY_COLUMNS, read_json, write_json


app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False, help="OpenCode Agent Evaluation Harness.")
console = Console()


def _load_prompt(prompt: str | None, prompt_file: Path | None) -> str:
    if prompt_file is not None:
        return prompt_file.read_text(encoding="utf-8")
    return prompt or "웹 검색 후 Knox 메일 리포트 에이전트 작성"


@app.command()
def run(
    repo: Annotated[Path, typer.Option("--repo", exists=True, file_okay=False, dir_okay=True, resolve_path=True)],
    count: Annotated[int, typer.Option("--count", "-n", min=1)] = 20,
    concurrency: Annotated[int, typer.Option("--concurrency", "-j", min=1)] = 1,
    prompt: Annotated[str | None, typer.Option("--prompt", "-P")] = None,
    prompt_file: Annotated[Path | None, typer.Option("--prompt-file", exists=True, file_okay=True, dir_okay=False, resolve_path=True)] = None,
    skill: Annotated[str, typer.Option("--skill", "-s")] = "impl",
    branch: Annotated[str, typer.Option("--branch", "-b")] = "HEAD",
    worktree_root: Annotated[Path | None, typer.Option("--worktree-root", file_okay=False, dir_okay=True)] = None,
    output_dir: Annotated[Path, typer.Option("--output-dir", file_okay=False, dir_okay=True)] = Path("results"),
    base_port: Annotated[int, typer.Option("--base-port", min=1, max=65535)] = 4096,
    opencode_version: Annotated[str, typer.Option("--opencode-version")] = "1.4.6",
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    model: Annotated[str | None, typer.Option("--model")] = None,
    server_start_timeout_seconds: Annotated[float, typer.Option("--server-start-timeout-seconds", min=0.1)] = 60.0,
    health_poll_interval_seconds: Annotated[float, typer.Option("--health-poll-interval-seconds", min=0.05)] = 1.0,
    cwd_check: Annotated[bool, typer.Option("--cwd-check/--no-cwd-check")] = True,
    restart_on_mismatch: Annotated[bool, typer.Option("--restart-on-mismatch/--no-restart-on-mismatch")] = True,
    max_server_restarts: Annotated[int, typer.Option("--max-server-restarts", min=0)] = 2,
    idle_quiet_seconds: Annotated[float, typer.Option("--idle-quiet-seconds", min=0.0)] = 10.0,
    hard_timeout_seconds: Annotated[float, typer.Option("--hard-timeout-seconds", min=0.1)] = 900.0,
    no_live: Annotated[bool, typer.Option("--no-live")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run a new evaluation batch."""
    options = BatchOptions(
        repo=repo,
        count=count,
        concurrency=concurrency,
        prompt=_load_prompt(prompt, prompt_file),
        skill=skill,
        branch=branch,
        worktree_root=worktree_root,
        output_dir=output_dir,
        base_port=base_port,
        opencode_version=opencode_version,
        provider=provider,
        model=model,
        server_start_timeout_seconds=server_start_timeout_seconds,
        health_poll_interval_seconds=health_poll_interval_seconds,
        cwd_check=cwd_check,
        restart_on_mismatch=restart_on_mismatch,
        max_server_restarts=max_server_restarts,
        idle_quiet_seconds=idle_quiet_seconds,
        hard_timeout_seconds=hard_timeout_seconds,
        no_live=no_live,
        json=json_output,
    )
    batch_dir, results = run_batch(options, stream=sys.stdout, console_print=console.print)
    failed = [result for result in results if result.status != "completed"]
    if json_output:
        sys.stdout.write(json.dumps({"type": "batch_completed", "batch_id": batch_dir.name, "path": str(batch_dir), "failed": len(failed)}, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    else:
        console.print(f"batch | completed | {batch_dir}")
    if failed:
        guard_failures = {"server_unhealthy", "server_version_mismatch", "cwd_mismatch", "server_restart_exhausted", "harness_error"}
        exit_code = 3 if any(result.failure_class in guard_failures for result in failed) else 1
        raise typer.Exit(exit_code)


@app.command()
def collect(batch_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False, dir_okay=True, resolve_path=True)]) -> None:
    """Collect local artifacts and recompute a compact summary."""
    runs_dir = batch_dir / "runs"
    rows = []
    for path in sorted(runs_dir.glob("*/run.json")):
        run_data = read_json(path)
        metrics = run_data.get("metrics", {})
        validation = run_data.get("validation", {})
        server_info = run_data.get("server_info", {})
        worktree = run_data.get("worktree", {})
        rows.append(
            {
                "batch_id": run_data.get("batch_id", batch_dir.name),
                "run_id": run_data.get("run_id"),
                "status": run_data.get("status"),
                "failure_class": run_data.get("failure_class"),
                "model": "",
                "provider": "",
                "opencode_version": server_info.get("requested_version", ""),
                "worktree_path": worktree.get("path", ""),
                "port": server_info.get("port", ""),
                "server_restart_count": metrics.get("server_restart_count", 0),
                "total_messages": metrics.get("total_messages", 0),
                "total_tool_calls": metrics.get("total_tool_calls", 0),
                "total_subagent_run": metrics.get("total_subagent_run", 0),
                "total_operational_ms": metrics.get("total_operational_ms", 0),
                "validation_passed": validation.get("validation_passed", False),
                "task_success": metrics.get("task_success", False),
                "error_message": run_data.get("error_message", ""),
            }
        )
    summary = {"batch_id": batch_dir.name, "runs": rows}
    write_json(batch_dir / "summary.json", summary)
    with (batch_dir / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    write_json(batch_dir / "collected.json", summary)
    console.print(f"collected | {len(rows)} runs | {batch_dir / 'summary.json'}")


@app.command()
def fetch(batch_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False, dir_okay=True, resolve_path=True)]) -> None:
    """Fetch remote instrumentation metrics placeholder."""
    output = batch_dir / "remote_metrics.json"
    write_json(output, {"batch_id": batch_dir.name, "remote_metrics": [], "note": "remote instrumentation not configured"})
    console.print(f"fetch | wrote | {output}")


@app.command()
def cleanup(
    manifest: Annotated[Path, typer.Argument(exists=True, file_okay=True, dir_okay=False, resolve_path=True)],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Remove manifest-owned temporary resources."""
    try:
        actions = cleanup_manifest(manifest, dry_run=dry_run)
    except Exception as exc:
        console.print(f"cleanup failed | {exc}")
        raise typer.Exit(4) from exc
    console.print(f"cleanup | {len(actions)} paths | {'dry-run' if dry_run else 'done'}")


@app.command()
def inspect(path: Annotated[Path, typer.Argument(exists=True, resolve_path=True)]) -> None:
    """Display a run or batch summary."""
    data_path = path
    if path.is_dir():
        data_path = path / "summary.json"
        if not data_path.exists():
            data_path = path / "run.json"
    data = read_json(data_path)
    if "runs" in data:
        table = Table("Run", "Status", "Failure", "Validation")
        for row in data.get("runs", []):
            table.add_row(str(row.get("run_id")), str(row.get("status")), str(row.get("failure_class", "")), str(row.get("validation_passed", "")))
        console.print(table)
    else:
        table = Table("Field", "Value")
        for key in ("run_id", "status", "failure_class", "error_message"):
            table.add_row(key, str(data.get(key, "")))
        console.print(table)


if __name__ == "__main__":
    app()
