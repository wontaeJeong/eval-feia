from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import httpx
import typer

from .cleanup import cleanup_manifest
from .models import DEFAULT_MODEL, DEFAULT_OPENCODE_VERSION, DEFAULT_PROMPT, DEFAULT_PROVIDER, DEFAULT_SKILL, RunConfig
from .orchestrator import BatchRunner
from .process import validate_opencode_version
from .reports import collect_summaries, write_json


app = typer.Typer(help="OpenCode agent evaluation harness.")


@app.command()
def run(
    repo: Annotated[Path, typer.Option("--repo", exists=True, file_okay=False, resolve_path=True)] = Path("."),
    count: Annotated[int, typer.Option("--count", "-n", min=1)] = 20,
    concurrency: Annotated[int, typer.Option("--concurrency", "-j", min=1)] = 1,
    prompt: Annotated[str, typer.Option("--prompt", "-P")] = DEFAULT_PROMPT,
    prompt_file: Annotated[Path | None, typer.Option("--prompt-file", exists=True, dir_okay=False)] = None,
    skill: Annotated[str, typer.Option("--skill", "-s")] = DEFAULT_SKILL,
    branch: Annotated[str, typer.Option("--branch", "-b")] = "HEAD",
    worktree_root: Annotated[Path | None, typer.Option("--worktree-root")] = None,
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("results"),
    base_port: Annotated[int, typer.Option("--base-port")] = 4096,
    opencode_version: Annotated[str, typer.Option("--opencode-version")] = DEFAULT_OPENCODE_VERSION,
    provider: Annotated[str, typer.Option("--provider")] = DEFAULT_PROVIDER,
    model: Annotated[str, typer.Option("--model")] = DEFAULT_MODEL,
    server_start_timeout_seconds: Annotated[float, typer.Option("--server-start-timeout-seconds")] = 30.0,
    health_poll_interval_seconds: Annotated[float, typer.Option("--health-poll-interval-seconds")] = 0.5,
    cwd_check: Annotated[bool, typer.Option("--cwd-check/--no-cwd-check")] = True,
    restart_on_mismatch: Annotated[bool, typer.Option("--restart-on-mismatch/--no-restart-on-mismatch")] = True,
    max_server_restarts: Annotated[int, typer.Option("--max-server-restarts", min=0)] = 2,
    idle_quiet_seconds: Annotated[float, typer.Option("--idle-quiet-seconds")] = 2.0,
    hard_timeout_seconds: Annotated[float, typer.Option("--hard-timeout-seconds")] = 1800.0,
    no_live: Annotated[bool, typer.Option("--no-live")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run a new evaluation batch."""
    try:
        validate_opencode_version(opencode_version)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--opencode-version") from exc
    actual_prompt = prompt_file.read_text() if prompt_file else prompt
    config = RunConfig(
        repo=repo,
        count=count,
        concurrency=concurrency,
        prompt=actual_prompt,
        prompt_file=prompt_file,
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
    records = BatchRunner(config, stream=sys.stdout).run()
    if any(record.status != "completed" and str(record.status) != "completed" for record in records):
        raise typer.Exit(1)


@app.command()
def collect(output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("results")) -> None:
    """Collect local artifacts and recompute summaries."""
    batches = collect_summaries(output_dir)
    typer.echo(f"collected {batches} batch(es) from {output_dir}")


@app.command()
def fetch(
    remote_url: Annotated[str | None, typer.Option("--remote-url")] = None,
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("results"),
) -> None:
    """Fetch remote instrumentation metrics."""
    if remote_url is None:
        typer.echo("no remote instrumentation URL provided")
        return
    response = httpx.get(remote_url, timeout=10.0)
    response.raise_for_status()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "remote_metrics.json"
    try:
        payload = response.json()
    except ValueError:
        payload = {"text": response.text}
    write_json(path, payload)
    typer.echo(str(path))


@app.command()
def cleanup(manifest: Annotated[Path, typer.Option("--manifest", exists=True, dir_okay=False)]) -> None:
    """Remove manifest-owned temp resources."""
    try:
        removed = cleanup_manifest(manifest)
    except Exception as exc:  # noqa: BLE001
        typer.echo(str(exc), err=True)
        raise typer.Exit(4) from exc
    for path in removed:
        typer.echo(str(path))


@app.command()
def inspect(path: Annotated[Path, typer.Argument(exists=True)]) -> None:
    """Display a run or batch summary."""
    typer.echo(path.read_text() if path.is_file() else str(path))


if __name__ == "__main__":
    app()
