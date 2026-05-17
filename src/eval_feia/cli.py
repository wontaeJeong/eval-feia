from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, Mapping, cast

import typer
from rich.console import Console

from .clean import CleanupResult, clean_resources, clean_results
from .config import EvalConfig, build_config
from .errors import CleanupSafetyError, ConfigError, EvalFeiaError, GitError, HealthError
from .listing import list_saved_runs, print_saved_runs, saved_runs_json
from .plain_table import print_plain_table
from .results_store import (
    complete_run_record,
    list_run_metadata,
    load_metadata,
    read_result_file,
    result_file_path,
    run_directory,
    start_run_record,
)
from .records import RunSummary
from .runner import RunOutcome, generate_run_id, run_evaluation
from .storage import (
    DB_ENV_VAR,
    VALID_STATUSES,
    backfill_from_output_dir,
    count_runs,
    default_db_path,
    format_storage_error,
    list_runs as list_indexed_runs,
)
from .summary import render_markdown_summary


app = typer.Typer(add_completion=False, help="REST-only opencode worktree evaluator.")
console = Console()


@app.command("run-eval")
def run_eval(
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
    run_id = generate_run_id()
    stored_output_dir = run_directory(run_id)
    run_console = Console(record=True)
    run_console.print(f"Run ID: {run_id}", markup=False)
    run_console.print(f"Output directory: {stored_output_dir}", markup=False, soft_wrap=True)
    start_run_record(
        run_id,
        cwd=Path.cwd(),
        branch=branch or "HEAD",
        label=label,
        command=command,
    )
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
        outcome = run_evaluation(eval_config, console=run_console, run_id=run_id)
    except ConfigError as exc:
        message = f"configuration error: {exc}"
        run_console.print(message, style="red")
        _finish_failed_cli_run(run_id, run_console, exc, message, exit_code=2)
        raise typer.Exit(2) from exc
    except HealthError as exc:
        message = f"opencode preflight failed: {exc}"
        run_console.print(message, style="red")
        _finish_failed_cli_run(run_id, run_console, exc, message, exit_code=3)
        raise typer.Exit(3) from exc
    except GitError as exc:
        message = f"git worktree setup failed: {exc}"
        run_console.print(message, style="red")
        _finish_failed_cli_run(run_id, run_console, exc, message, exit_code=4)
        raise typer.Exit(4) from exc
    except KeyboardInterrupt as exc:
        message = "interrupted"
        run_console.print(message, style="yellow")
        _finish_failed_cli_run(
            run_id,
            run_console,
            None,
            message,
            exit_code=130,
            kind="interrupted",
        )
        raise typer.Exit(130) from exc
    except EvalFeiaError as exc:
        message = f"eval-feia failed: {exc}"
        run_console.print(message, style="red")
        _finish_failed_cli_run(run_id, run_console, exc, message, exit_code=1)
        raise typer.Exit(1) from exc
    exit_code = 0 if outcome.passed else 1
    _finish_completed_cli_run(run_id, run_console, outcome, exit_code=exit_code)
    raise typer.Exit(exit_code)


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


def _list_run_artifacts_command(
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Show only the most recent N generated run artifacts."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Generated run artifact root to inspect."),
    ] = None,
    status: Annotated[str | None, typer.Option("--status", help="Filter by indexed run status.")] = None,
    branch: Annotated[str | None, typer.Option("--branch", help="Filter by indexed branch/base ref.")] = None,
    label: Annotated[str | None, typer.Option("--label", help="Filter by indexed run label.")] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print generated run artifacts as a JSON array."),
    ] = False,
) -> None:
    """List generated run artifacts."""
    if limit is not None and limit < 1:
        console.print("--limit must be greater than zero", style="red")
        raise typer.Exit(2)
    if _should_use_sqlite_index(status=status, branch=branch, label=label):
        _list_indexed_run_artifacts(
            limit=limit or 20,
            output_dir=output_dir,
            status=status,
            branch=branch,
            label=label,
            json_output=json_output,
        )
        raise typer.Exit(0)

    runs = list_saved_runs(output_root=output_dir, limit=limit)
    if json_output:
        typer.echo(saved_runs_json(runs))
        raise typer.Exit(0)
    print_saved_runs(console, runs)
    raise typer.Exit(0)


def _should_use_sqlite_index(*, status: str | None, branch: str | None, label: str | None) -> bool:
    return bool(os.environ.get(DB_ENV_VAR) or status is not None or branch is not None or label is not None)


def _list_indexed_run_artifacts(
    *,
    limit: int,
    output_dir: Path | None,
    status: str | None,
    branch: str | None,
    label: str | None,
    json_output: bool,
) -> None:
    if status is not None and status not in VALID_STATUSES:
        console.print(
            "invalid --status; expected one of " + ", ".join(sorted(VALID_STATUSES)),
            style="red",
        )
        raise typer.Exit(2)
    output_root = (output_dir or Path(".eval-feia/runs")).expanduser().resolve(strict=False)
    db_path = default_db_path(output_root)
    try:
        if count_runs(db_path) == 0:
            backfill_from_output_dir(db_path, output_root)
        rows = list_indexed_runs(db_path, limit=limit, status=status, branch=branch, label=label)
    except Exception as exc:
        console.print(format_storage_error(exc, db_path), style="red")
        raise typer.Exit(6) from exc

    if json_output:
        console.print(json.dumps(rows, ensure_ascii=False, sort_keys=True), markup=False, soft_wrap=True)
        return
    print_plain_table(
        console,
        ("ID", "STATUS", "BRANCH/LABEL", "CWD", "STARTED", "ENDED", "DURATION", "OUTPUT"),
        [_indexed_run_row(row) for row in rows],
    )


def _indexed_run_row(row: Mapping[str, object]) -> tuple[str, ...]:
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


def _display_cwd(row: Mapping[str, object]) -> str:
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


app.command("list-run-artifacts")(_list_run_artifacts_command)


def _finish_completed_cli_run(
    run_id: str,
    run_console: Console,
    outcome: RunOutcome,
    *,
    exit_code: int,
) -> None:
    output_text = _outcome_output_text(outcome)
    summary_text = _outcome_summary_text(outcome, output_text)
    status = "success" if exit_code == 0 else "failed"
    extra: dict[str, Any] = {}
    artifacts_dir = getattr(outcome, "output_dir", None)
    if isinstance(artifacts_dir, Path):
        extra["artifacts_dir"] = str(artifacts_dir)
        _copy_text_artifacts(run_id, artifacts_dir)
    complete_run_record(
        run_id,
        status=status,
        exit_code=exit_code,
        output_text=output_text,
        summary_text=summary_text,
        stdout_text=run_console.export_text(),
        stderr_text="",
        extra=extra,
    )


def _finish_failed_cli_run(
    run_id: str,
    run_console: Console,
    exc: EvalFeiaError | None,
    message: str,
    *,
    exit_code: int,
    kind: str | None = None,
) -> None:
    error = exc.record.to_dict() if exc is not None else {"kind": kind or "error", "message": message}
    complete_run_record(
        run_id,
        status="failed",
        exit_code=exit_code,
        output_text=message + "\n",
        summary_text=message + "\n",
        stdout_text=run_console.export_text(),
        stderr_text=message + "\n",
        error=error,
    )


def _outcome_output_text(outcome: RunOutcome) -> str:
    output_dir = getattr(outcome, "output_dir", None)
    summary = getattr(outcome, "summary", None)
    if not isinstance(output_dir, Path) or not isinstance(summary, dict):
        return ""
    run_summary = cast(RunSummary, summary)

    chunks: list[str] = []
    candidates = run_summary.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            candidate_id = candidate.get("candidate_id")
            if not isinstance(candidate_id, str) or not candidate_id:
                continue
            file_name = "final-output.md"
            candidate_summary = candidate.get("summary")
            if isinstance(candidate_summary, dict):
                configured_file = candidate_summary.get("final_output_file")
                if isinstance(configured_file, str) and configured_file:
                    file_name = configured_file
            final_output = output_dir / "candidates" / candidate_id / file_name
            if not final_output.exists():
                continue
            text = final_output.read_text(encoding="utf-8")
            if len(candidates) == 1:
                chunks.append(text)
            else:
                chunks.append(f"# {candidate_id}\n\n{text}")
    if chunks:
        return "\n".join(chunk.rstrip() for chunk in chunks).rstrip() + "\n"

    summary_file = output_dir / "run-summary.md"
    if summary_file.exists():
        return summary_file.read_text(encoding="utf-8")
    return render_markdown_summary(run_summary)


def _outcome_summary_text(outcome: RunOutcome, fallback: str) -> str:
    output_dir = getattr(outcome, "output_dir", None)
    summary = getattr(outcome, "summary", None)
    if isinstance(output_dir, Path):
        summary_file = output_dir / "run-summary.md"
        if summary_file.exists():
            return summary_file.read_text(encoding="utf-8")
    if isinstance(summary, dict):
        return render_markdown_summary(cast(RunSummary, summary))
    return fallback


def _copy_text_artifacts(run_id: str, artifacts_dir: Path) -> None:
    stored_dir = run_directory(run_id)
    for name in ("manifest.json", "run-summary.json", "run-summary.md"):
        source = artifacts_dir / name
        if source.exists() and source.is_file():
            (stored_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


@app.command("list-stored-results")
def list_stored_results() -> None:
    """List stored run results, newest first."""
    rows = [
        (
            str(record.get("run_id") or ""),
            str(record.get("created_at") or ""),
            str(record.get("status") or "unknown"),
            str(record.get("branch") or ""),
            str(record.get("label") or ""),
            str(record.get("cwd") or ""),
            str(record.get("output_dir") or ""),
        )
        for record in list_run_metadata()
    ]
    print_plain_table(
        console,
        ("RUN_ID", "CREATED_AT", "STATUS", "BRANCH", "LABEL", "CWD", "OUTPUT_DIR"),
        rows,
    )


@app.command("show-stored-result")
def show_stored_result(run_id: Annotated[str, typer.Argument(help="Run ID to show.")]) -> None:
    """Show metadata and a short summary for one stored run."""
    try:
        metadata = load_metadata(run_id)
        summary = _result_summary_preview(run_id)
    except Exception as exc:
        _raise_results_error(exc)
    for key in (
        "run_id",
        "status",
        "created_at",
        "finished_at",
        "cwd",
        "branch",
        "label",
        "command",
        "exit_code",
        "output_dir",
    ):
        value = metadata.get(key)
        console.print(f"{key}: {'' if value is None else value}", markup=False, soft_wrap=True)
    console.print("summary:", markup=False)
    console.print(summary, markup=False)


@app.command("print-stored-result-path")
def print_stored_result_path(run_id: Annotated[str, typer.Argument(help="Run ID to locate.")]) -> None:
    """Print only the stored run output directory."""
    try:
        metadata = load_metadata(run_id)
    except Exception as exc:
        _raise_results_error(exc)
    console.print(
        str(Path(str(metadata["output_dir"])).resolve(strict=False)),
        markup=False,
        soft_wrap=True,
    )


@app.command("print-stored-result-file")
def print_stored_result_file(
    run_id: Annotated[str, typer.Argument(help="Run ID to read from.")],
    file: Annotated[
        str | None,
        typer.Argument(help="File inside the run directory. Defaults to output.txt."),
    ] = None,
) -> None:
    """Print a stored result file."""
    try:
        content = read_result_file(run_id, file)
    except Exception as exc:
        _raise_results_error(exc)
    console.print(content, markup=False, end="", soft_wrap=True)


def _result_summary_preview(run_id: str, *, limit: int = 4000) -> str:
    try:
        path = result_file_path(run_id, "summary.txt")
    except Exception:
        path = result_file_path(run_id, "output.txt")
    text = path.read_text(encoding="utf-8")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n..."


def _raise_results_error(exc: Exception) -> None:
    console.print(f"results error: {exc}", style="red")
    raise typer.Exit(1) from exc


@app.command("clean-run-artifacts")
def clean_run_artifacts(
    manifest: Annotated[
        Path,
        typer.Argument(help="Manifest file for generated run artifacts.", metavar="MANIFEST"),
    ],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print planned deletions only.")] = False,
    force: Annotated[bool, typer.Option("--force", help="Continue after non-critical errors.")] = False,
    delete_index: Annotated[
        bool,
        typer.Option(
            "--delete-index",
            help="Also delete the manifest-recorded default SQLite metadata index database.",
        ),
    ] = False,
) -> None:
    """Remove manifest-recorded generated worktrees and run artifacts."""
    try:
        cleanup_result = clean_resources(
            manifest,
            dry_run=dry_run,
            force=force,
            remove_db=delete_index,
        )
    except CleanupSafetyError as exc:
        console.print(f"cleanup safety check failed: {exc}", style="red")
        raise typer.Exit(5) from exc
    except Exception as exc:
        console.print(f"cleanup failed: {exc}", style="red")
        raise typer.Exit(5) from exc
    _print_cleanup_result(cleanup_result, dry_run=dry_run)


@app.command("clean-stored-results")
def clean_stored_results(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print planned deletions only.")] = False,
) -> None:
    """Remove the configured stored-results history root."""
    try:
        cleanup_result = clean_results(dry_run=dry_run)
    except CleanupSafetyError as exc:
        console.print(f"cleanup safety check failed: {exc}", style="red")
        raise typer.Exit(5) from exc
    except Exception as exc:
        console.print(f"cleanup failed: {exc}", style="red")
        raise typer.Exit(5) from exc
    _print_cleanup_result(cleanup_result, dry_run=dry_run)


def _print_cleanup_result(cleanup_result: CleanupResult, *, dry_run: bool) -> None:
    for action in cleanup_result.actions:
        prefix = "would remove" if dry_run else "removed"
        console.print(f"{prefix} {action.kind}: {action.path}", soft_wrap=True)
    for warning in cleanup_result.warnings:
        console.print(f"warning: {warning}", style="yellow")
    if cleanup_result.errors:
        for error in cleanup_result.errors:
            console.print(error, style="red")
        raise typer.Exit(5)
    raise typer.Exit(0)


if __name__ == "__main__":
    app()
