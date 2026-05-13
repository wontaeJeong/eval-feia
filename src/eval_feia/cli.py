from __future__ import annotations

import json
import ipaddress
import socket
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

import typer
import httpx
from rich.console import Console
from rich.table import Table

from .cleanup import cleanup_from_manifest
from .live import JsonProgressSink, JsonlWriter, RichProgressSink
from .models import BatchSpec, DEFAULT_PROMPT, DEFAULT_SKILL
from .orchestrator import BatchRunner
from .process import validate_opencode_version
from .reports import load_run_records, write_summary


app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich", pretty_exceptions_show_locals=False)
console = Console()


def _prompt_text(prompt: str | None, prompt_file: Path | None) -> str:
    if prompt_file is not None:
        return prompt_file.read_text(encoding="utf-8")
    return prompt or DEFAULT_PROMPT


@app.command()
def run(
    repo: Annotated[Path, typer.Option("--repo", exists=True, file_okay=False, dir_okay=True, resolve_path=True, help="Repository to evaluate.")],
    count: Annotated[int, typer.Option("--count", "-n", min=1)] = 20,
    concurrency: Annotated[int, typer.Option("--concurrency", "-j", min=1)] = 1,
    prompt: Annotated[str | None, typer.Option("--prompt", "-P")] = None,
    prompt_file: Annotated[Path | None, typer.Option("--prompt-file", exists=True, dir_okay=False, resolve_path=True)] = None,
    skill: Annotated[str, typer.Option("--skill", "-s")] = DEFAULT_SKILL,
    branch: Annotated[str, typer.Option("--branch", "-b")] = "HEAD",
    worktree_root: Annotated[Path | None, typer.Option("--worktree-root", file_okay=False, resolve_path=True)] = None,
    output_dir: Annotated[Path, typer.Option("--output-dir", file_okay=False, resolve_path=True)] = Path("results"),
    base_port: Annotated[int, typer.Option("--base-port", min=1, max=65535)] = 4096,
    opencode_version: Annotated[str, typer.Option("--opencode-version")] = "1.4.6",
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    model: Annotated[str | None, typer.Option("--model")] = None,
    server_start_timeout_seconds: Annotated[float, typer.Option("--server-start-timeout-seconds", min=0.1)] = 60.0,
    health_poll_interval_seconds: Annotated[float, typer.Option("--health-poll-interval-seconds", min=0.01)] = 1.0,
    cwd_check: Annotated[bool, typer.Option("--cwd-check/--no-cwd-check")] = True,
    restart_on_mismatch: Annotated[bool, typer.Option("--restart-on-mismatch/--no-restart-on-mismatch")] = True,
    max_server_restarts: Annotated[int, typer.Option("--max-server-restarts", min=0)] = 2,
    idle_quiet_seconds: Annotated[float, typer.Option("--idle-quiet-seconds", min=0)] = 10.0,
    hard_timeout_seconds: Annotated[float, typer.Option("--hard-timeout-seconds", min=1)] = 1800.0,
    no_live: Annotated[bool, typer.Option("--no-live", help="Disable Rich live output.")] = False,
    json_mode: Annotated[bool, typer.Option("--json", help="Emit progress as JSONL only.")] = False,
) -> None:
    try:
        validate_opencode_version(opencode_version)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--opencode-version") from exc
    sink = JsonProgressSink(JsonlWriter()) if json_mode else RichProgressSink(console)
    spec = BatchSpec(
        repo=repo,
        count=count,
        concurrency=concurrency,
        prompt=_prompt_text(prompt, prompt_file),
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
        live=not no_live,
        json=json_mode,
    )
    records, batch_dir = BatchRunner(spec, sink=sink).run()
    if not json_mode:
        console.print(f"batch | complete | {batch_dir}")
    if any(record.status != "completed" for record in records):
        raise typer.Exit(1)


@app.command()
def collect(
    batch_dir: Annotated[Path, typer.Option("--batch-dir", exists=True, file_okay=False, resolve_path=True)],
) -> None:
    records = load_run_records(batch_dir)
    rows = [_summary_row_from_dict(record) for record in records]
    write_summary(batch_dir, rows)
    console.print(f"collect | summary | {batch_dir / 'summary.json'}")


@app.command()
def fetch(
    batch_dir: Annotated[Path, typer.Option("--batch-dir", exists=True, file_okay=False, resolve_path=True)],
    url: Annotated[str | None, typer.Option("--url", help="Remote instrumentation URL.")] = None,
) -> None:
    if url is None:
        payload = {"batch_dir": str(batch_dir), "url": None, "status": "skipped"}
    else:
        _validate_fetch_url(url)
        response = httpx.get(url, params={"batch_dir": str(batch_dir)}, timeout=30.0)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        data: object = response.json() if "json" in content_type else response.text
        payload = {"batch_dir": str(batch_dir), "url": url, "status": "fetched", "status_code": response.status_code, "data": data}
    (batch_dir / "fetch.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    console.print(f"fetch | {payload['status']} | {batch_dir / 'fetch.json'}")


@app.command()
def cleanup(
    manifest: Annotated[Path, typer.Option("--manifest", exists=True, dir_okay=False, resolve_path=True)],
) -> None:
    result = cleanup_from_manifest(manifest)
    console.print(json.dumps(result, ensure_ascii=False))
    if not result.get("ok"):
        raise typer.Exit(4)


@app.command()
def inspect(
    batch_dir: Annotated[Path, typer.Option("--batch-dir", exists=True, file_okay=False, resolve_path=True)],
    json_mode: Annotated[bool, typer.Option("--json", help="Print raw JSON summary.")] = False,
) -> None:
    summary_path = batch_dir / "summary.json"
    if json_mode:
        console.print(summary_path.read_text(encoding="utf-8"))
        return
    data = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {"runs": []}
    table = Table(title="eval-feia summary")
    for column in ["Run", "Status", "Failure", "Task", "Messages", "Tools"]:
        table.add_column(column)
    for row in data.get("runs", []):
        table.add_row(
            str(row.get("run_id", "")),
            str(row.get("status", "")),
            str(row.get("failure_class", "")),
            str(row.get("task_success", "")),
            str(row.get("total_messages", "")),
            str(row.get("total_tool_calls", "")),
        )
    console.print(table)


def _summary_row_from_dict(record: dict[str, Any]) -> dict[str, Any]:
    metrics = record.get("metrics", {})
    server = record.get("server_info", {})
    worktree = record.get("worktree", {})
    return {
        "batch_id": record.get("batch_id", ""),
        "run_id": record.get("run_id", ""),
        "status": record.get("status", ""),
        "failure_class": record.get("failure_class", ""),
        "model": "",
        "provider": "",
        "opencode_version": server.get("requested_version", ""),
        "worktree_path": worktree.get("path", ""),
        "port": server.get("port", ""),
        "server_restart_count": metrics.get("server_restart_count", 0),
        "total_messages": metrics.get("total_messages", 0),
        "total_tool_calls": metrics.get("total_tool_calls", 0),
        "total_subagent_run": metrics.get("total_subagent_run", 0),
        "total_operational_ms": metrics.get("total_operational_ms", 0),
        "validation_passed": metrics.get("validation_passed", False),
        "task_success": metrics.get("task_success", False),
        "error_message": record.get("error_message") or "",
    }


def _validate_fetch_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise typer.BadParameter("fetch URL must use https", param_hint="--url")
    if not parsed.hostname:
        raise typer.BadParameter("fetch URL must include a hostname", param_hint="--url")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise typer.BadParameter(f"fetch URL hostname could not be resolved: {parsed.hostname}", param_hint="--url") from exc
    for address in addresses:
        host = address[4][0]
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise typer.BadParameter("fetch URL must not resolve to a private, loopback, or reserved address", param_hint="--url")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
