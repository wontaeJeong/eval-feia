# pyright: reportMissingImports=false
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

from .cleanup import CleanupError, cleanup_from_manifest
from .live import RichLiveDisplay
from .models import DEFAULT_PROMPT, DEFAULT_SKILL, RunOptions
from .orchestrator import run_batch
from .reports import collect_existing_batch, read_json, write_json

app = typer.Typer(help="OpenCode Agent Evaluation Harness")
console = Console()


@app.command()
def run(
    repo: Path = typer.Option(Path("."), "--repo", help="Repository path"),
    count: int = typer.Option(20, "--count", "-n", min=1),
    concurrency: int = typer.Option(1, "--concurrency", "-j", min=1),
    prompt: str = typer.Option(DEFAULT_PROMPT, "--prompt", "-P"),
    prompt_file: Optional[Path] = typer.Option(None, "--prompt-file"),
    skill: str = typer.Option(DEFAULT_SKILL, "--skill", "-s"),
    branch: str = typer.Option("HEAD", "--branch", "-b"),
    worktree_root: Optional[Path] = typer.Option(None, "--worktree-root"),
    output_dir: Path = typer.Option(Path("results"), "--output-dir"),
    base_port: int = typer.Option(4096, "--base-port"),
    opencode_version: str = typer.Option("1.4.6", "--opencode-version"),
    provider: str = typer.Option("openai", "--provider"),
    model: str = typer.Option("gpt-5.5", "--model"),
    server_start_timeout_seconds: float = typer.Option(30.0, "--server-start-timeout-seconds"),
    health_poll_interval_seconds: float = typer.Option(0.5, "--health-poll-interval-seconds"),
    cwd_check: bool = typer.Option(True, "--cwd-check/--no-cwd-check"),
    restart_on_mismatch: bool = typer.Option(True, "--restart-on-mismatch/--no-restart-on-mismatch"),
    max_server_restarts: int = typer.Option(2, "--max-server-restarts"),
    idle_quiet_seconds: float = typer.Option(30.0, "--idle-quiet-seconds"),
    hard_timeout_seconds: float = typer.Option(1800.0, "--hard-timeout-seconds"),
    no_live: bool = typer.Option(False, "--no-live"),
    json_output: bool = typer.Option(False, "--json"),
    fake_server_url: Optional[str] = typer.Option(None, "--fake-server-url", hidden=True),
) -> None:
    """Run a new evaluation batch."""
    prompt_text = prompt_file.read_text(encoding="utf-8") if prompt_file else prompt
    options = RunOptions(
        repo=repo,
        count=count,
        concurrency=concurrency,
        prompt=prompt_text,
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
        json_output=json_output,
        fake_server_url=fake_server_url,
    )
    try:
        if json_output or no_live:
            result = run_batch(options)
        else:
            with RichLiveDisplay(enabled=True) as display:
                result = run_batch(options, display=display)
    except Exception as exc:
        if json_output:
            typer.echo(json.dumps({"type": "harness_error", "error": str(exc)}, ensure_ascii=False))
        else:
            console.print(f"[red]eval-feia failed:[/red] {exc}")
        raise typer.Exit(3) from exc
    if not json_output:
        console.print(f"batch: {result.batch_dir}")
    raise typer.Exit(1 if result.failed_count else 0)


@app.command()
def collect(batch_dir: Path = typer.Argument(..., help="Batch result directory")) -> None:
    """Collect local artifacts and recompute summaries."""
    if not (batch_dir / "manifest.json").exists():
        console.print(f"collect failed: missing manifest.json under {batch_dir}")
        raise typer.Exit(2)
    manifest = read_json(batch_dir / "manifest.json")
    runs = collect_existing_batch(batch_dir)
    rows = []
    for run_data in runs:
        rows.append(_row_from_run_json(run_data, manifest))
    summary = {"batch_dir": str(batch_dir), "total_runs": len(rows), "runs": rows}
    write_json(batch_dir / "summary.json", summary)
    _write_collect_csv(batch_dir / "summary.csv", rows)
    console.print(f"collected {len(rows)} runs from {batch_dir}")


@app.command()
def fetch(
    batch_dir: Path = typer.Argument(..., help="Batch result directory"),
    url: Optional[str] = typer.Option(None, "--url", help="Remote instrumentation URL"),
) -> None:
    """Fetch remote instrumentation metrics when a source is configured."""
    if not url:
        write_json(batch_dir / "remote_metrics.json", {"fetched": False, "reason": "no url configured"})
        console.print("remote metrics: no url configured")
        return
    response = httpx.get(url, timeout=10.0)
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError:
        payload = {"text": response.text}
    write_json(batch_dir / "remote_metrics.json", {"fetched": True, "url": url, "payload": payload})
    console.print("remote metrics fetched")


@app.command()
def cleanup(manifest_path: Path = typer.Argument(..., help="Path to manifest.json")) -> None:
    """Remove manifest-owned temporary resources."""
    if not manifest_path.exists():
        console.print(f"cleanup failed: missing manifest {manifest_path}")
        raise typer.Exit(4)
    try:
        removed = cleanup_from_manifest(manifest_path)
    except CleanupError as exc:
        console.print(f"cleanup failed: {exc}")
        raise typer.Exit(4) from exc
    console.print(f"removed {len(removed)} manifest-owned paths")


@app.command()
def inspect(path: Path = typer.Argument(..., help="Batch dir, run dir, or JSON artifact")) -> None:
    """Display a run or batch summary."""
    target = path
    if path.is_dir() and (path / "summary.json").exists():
        target = path / "summary.json"
    elif path.is_dir() and (path / "run.json").exists():
        target = path / "run.json"
    if not target.exists():
        console.print(f"inspect failed: missing {target}")
        raise typer.Exit(2)
    data = read_json(target)
    table = Table(title=str(target))
    table.add_column("Field")
    table.add_column("Value")
    for key in ("batch_id", "run_id", "status", "failure_class", "total_runs", "completed", "failed"):
        if key in data:
            table.add_row(key, str(data[key]))
    if "runs" in data and isinstance(data["runs"], list):
        table.add_row("runs", str(len(data["runs"])))
    console.print(table)


def _row_from_run_json(run_data: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    metrics = run_data.get("metrics", {}) if isinstance(run_data.get("metrics"), dict) else {}
    validation = run_data.get("validation", {}) if isinstance(run_data.get("validation"), dict) else {}
    worktree = run_data.get("worktree", {}) if isinstance(run_data.get("worktree"), dict) else {}
    server_info = run_data.get("server_info", {}) if isinstance(run_data.get("server_info"), dict) else {}
    return {
        "batch_id": run_data.get("batch_id", manifest.get("batch_id", "")),
        "run_id": run_data.get("run_id", ""),
        "status": run_data.get("status", ""),
        "failure_class": run_data.get("failure_class", ""),
        "model": "",
        "provider": "",
        "opencode_version": manifest.get("opencode_version", ""),
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


def _write_collect_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    import csv

    columns = [
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
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
