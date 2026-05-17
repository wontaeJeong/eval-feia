from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .clean import clean_resources
from .config import EvalConfig, build_config
from .errors import CleanupSafetyError, ConfigError, EvalFeiaError, GitError, HealthError
from .plain_table import print_plain_table
from .runner import run_evaluation
from .storage import (
    DB_ENV_VAR,
    VALID_STATUSES,
    backfill_from_output_dir,
    count_runs,
    default_db_path,
    format_storage_error,
    list_runs,
)


app = typer.Typer(
    add_completion=False,
    help=(
        "REST-only opencode worktree evaluator. Run metadata is indexed in SQLite at "
        f"<output-root>/eval-feia.sqlite3; override with {DB_ENV_VAR}."
    ),
)
console = Console()


@app.command()
def run(
    prompt: Annotated[
        str | None,
        typer.Argument(
            help="Prompt text. Omit when using --prompt-file.",
            metavar="PROMPT",
        ),
    ] = None,
    server_url: Annotated[
        str | None,
        typer.Option(
            "--server-url",
            help="opencode server URL.",
            show_default="http://127.0.0.1:4096",
        ),
    ] = None,
    repo: Annotated[
        Path | None,
        typer.Option("--repo", help="Git repository path.", show_default="current directory"),
    ] = None,
    branch: Annotated[
        str | None,
        typer.Option(
            "--branch",
            help="Git branch/ref to evaluate.",
            show_default="HEAD",
        ),
    ] = None,
    attempts: Annotated[
        int | None,
        typer.Option(
            "--attempts",
            help="Number of evaluation attempts/candidates.",
            show_default="1",
        ),
    ] = None,
    prompt_file: Annotated[Path | None, typer.Option("--prompt-file", help="Prompt file.")] = None,
    label: Annotated[
        str | None,
        typer.Option("--label", help="Run-level human-readable label."),
    ] = None,
    command: Annotated[
        str | None,
        typer.Option(
            "--command",
            help="Run an opencode slash command; the prompt is sent as command arguments.",
        ),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help=(
                "Run output root. SQLite index defaults to this directory/"
                f"eval-feia.sqlite3 unless {DB_ENV_VAR} is set."
            ),
        ),
    ] = None,
) -> None:
    """Create worktrees, execute opencode sessions, collect results, and summarize."""
    try:
        eval_config = _build_run_config(
            server_url=server_url,
            repo=repo,
            base_ref=branch,
            attempts=attempts,
            prompt=prompt,
            prompt_file=prompt_file,
            label=label,
            command=command,
            output_dir=output_dir,
        )
        outcome = run_evaluation(eval_config, console=console)
    except ConfigError as exc:
        console.print(f"configuration error: {exc}", style="red")
        raise typer.Exit(2) from exc
    except HealthError as exc:
        console.print(f"opencode preflight failed: {exc}", style="red")
        raise typer.Exit(3) from exc
    except GitError as exc:
        console.print(f"git worktree setup failed: {exc}", style="red")
        raise typer.Exit(4) from exc
    except KeyboardInterrupt as exc:
        console.print("interrupted", style="yellow")
        raise typer.Exit(130) from exc
    except EvalFeiaError as exc:
        console.print(f"eval-feia failed: {exc}", style="red")
        raise typer.Exit(1) from exc
    raise typer.Exit(0 if outcome.passed else 1)


def _build_run_config(
    *,
    server_url: str | None,
    repo: Path | None,
    base_ref: str | None,
    attempts: int | None,
    prompt: str | None,
    prompt_file: Path | None,
    label: str | None,
    command: str | None,
    output_dir: Path | None,
) -> EvalConfig:
    _validate_prompt_sources(prompt, prompt_file)
    return build_config(
        server_url=server_url,
        repo=repo,
        base_ref=base_ref,
        candidates=attempts,
        prompt=prompt,
        prompt_file=prompt_file,
        label=label,
        command=command,
        output_dir=output_dir,
    )


def _validate_prompt_sources(prompt: str | None, prompt_file: Path | None) -> None:
    prompt_sources = [
        ("PROMPT argument", prompt),
        ("--prompt-file", prompt_file),
    ]
    provided_prompt_sources = [name for name, value in prompt_sources if value is not None]
    if len(provided_prompt_sources) > 1:
        raise ConfigError(
            "provide only one prompt source: " + ", ".join(provided_prompt_sources)
        )


@app.command()
def clean(
    manifest: Annotated[
        Path,
        typer.Argument(help="Manifest file to clean.", metavar="MANIFEST"),
    ],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print planned deletions only.")] = False,
    force: Annotated[bool, typer.Option("--force", help="Continue after non-critical errors.")] = False,
    db: Annotated[
        bool,
        typer.Option(
            "--db",
            help=f"Also delete the SQLite metadata index database ({DB_ENV_VAR} overrides path).",
        ),
    ] = False,
) -> None:
    """Remove only manifest-recorded worktrees and run artifacts."""
    try:
        result = clean_resources(manifest, dry_run=dry_run, force=force, remove_db=db)
    except CleanupSafetyError as exc:
        console.print(f"cleanup safety check failed: {exc}", style="red")
        raise typer.Exit(5) from exc
    except Exception as exc:
        console.print(f"cleanup failed: {exc}", style="red")
        raise typer.Exit(5) from exc

    for action in result.actions:
        prefix = "would remove" if dry_run else "removed"
        console.print(f"{prefix} {action.kind}: {action.path}")
    for warning in result.warnings:
        console.print(f"warning: {warning}", style="yellow")
    if result.errors:
        for error in result.errors:
            console.print(error, style="red")
        raise typer.Exit(5)
    raise typer.Exit(0)


@app.command("list")
def list_command(
    limit: Annotated[int, typer.Option("--limit", help="Maximum number of runs to show.")] = 20,
    status: Annotated[str | None, typer.Option("--status", help="Filter by run status.")] = None,
    branch: Annotated[str | None, typer.Option("--branch", help="Filter by branch/base ref.")] = None,
    label: Annotated[str | None, typer.Option("--label", help="Filter by run label.")] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print a JSON array instead of a table."),
    ] = False,
) -> None:
    """List recent runs from the local SQLite metadata index."""
    _list_runs_command(
        limit=limit,
        status=status,
        branch=branch,
        label=label,
        json_output=json_output,
    )


@app.command("ls")
def ls_command(
    limit: Annotated[int, typer.Option("--limit", help="Maximum number of runs to show.")] = 20,
    status: Annotated[str | None, typer.Option("--status", help="Filter by run status.")] = None,
    branch: Annotated[str | None, typer.Option("--branch", help="Filter by branch/base ref.")] = None,
    label: Annotated[str | None, typer.Option("--label", help="Filter by run label.")] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print a JSON array instead of a table."),
    ] = False,
) -> None:
    """Alias for list."""
    _list_runs_command(
        limit=limit,
        status=status,
        branch=branch,
        label=label,
        json_output=json_output,
    )


def _list_runs_command(
    *,
    limit: int,
    status: str | None,
    branch: str | None,
    label: str | None,
    json_output: bool,
) -> None:
    if limit < 1:
        console.print("--limit must be at least 1", style="red")
        raise typer.Exit(2)
    if status is not None and status not in VALID_STATUSES:
        console.print(
            "invalid --status; expected one of " + ", ".join(sorted(VALID_STATUSES)),
            style="red",
        )
        raise typer.Exit(2)

    output_root = Path(".eval-feia/runs").expanduser().resolve(strict=False)
    db_path = default_db_path(output_root)
    try:
        if count_runs(db_path) == 0:
            backfill_from_output_dir(db_path, output_root)
        rows = list_runs(db_path, limit=limit, status=status, branch=branch, label=label)
    except Exception as exc:
        console.print(format_storage_error(exc, db_path), style="red")
        raise typer.Exit(6) from exc

    if json_output:
        console.print(json.dumps(rows, ensure_ascii=False, sort_keys=True), markup=False, soft_wrap=True)
        raise typer.Exit(0)

    print_plain_table(
        console,
        ("ID", "STATUS", "BRANCH/LABEL", "CWD", "STARTED", "ENDED", "DURATION", "OUTPUT"),
        [_list_row(row) for row in rows],
    )
    raise typer.Exit(0)


def _list_row(row: dict[str, object]) -> tuple[str, ...]:
    branch_or_label = str(row.get("label") or row.get("branch") or "")
    return (
        str(row.get("id") or "")[:12],
        str(row.get("status") or ""),
        branch_or_label,
        _display_cwd(row),
        str(row.get("started_at") or ""),
        str(row.get("ended_at") or ""),
        _format_duration(row.get("duration_ms")),
        str(row.get("output_dir") or ""),
    )


def _display_cwd(row: dict[str, object]) -> str:
    value = row.get("cwd") or row.get("repo_root")
    if not value:
        return ""
    path = Path(str(value))
    return path.name or str(path)


def _format_duration(value: object) -> str:
    if value is None:
        return ""
    try:
        duration_ms = int(value) if isinstance(value, int | str) else int(str(value))
    except (TypeError, ValueError):
        return ""
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    return f"{duration_ms / 1000:.1f}s"


if __name__ == "__main__":
    app()
