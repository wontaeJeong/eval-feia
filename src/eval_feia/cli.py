from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from .clean import clean_resources, clean_results
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
from .runner import generate_run_id, run_evaluation
from .summary import render_markdown_summary


app = typer.Typer(add_completion=False, help="REST-only opencode worktree evaluator.")
results_app = typer.Typer(add_completion=False, help="Inspect stored eval-feia results.")
app.add_typer(results_app, name="results")
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
    output_dir: Annotated[Path | None, typer.Option("--output-dir", help="Run output root.")] = None,
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


def _list_runs_command(
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Show only the most recent N saved runs."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Run output root to inspect."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print saved runs as a JSON array."),
    ] = False,
) -> None:
    """List saved run results."""
    if limit is not None and limit < 1:
        console.print("--limit must be greater than zero", style="red")
        raise typer.Exit(2)

    runs = list_saved_runs(output_root=output_dir, limit=limit)
    if json_output:
        typer.echo(saved_runs_json(runs))
        raise typer.Exit(0)
    print_saved_runs(console, runs)
    raise typer.Exit(0)


app.command("list")(_list_runs_command)
app.command("ls")(_list_runs_command)


def _finish_completed_cli_run(
    run_id: str,
    run_console: Console,
    outcome: Any,
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


def _outcome_output_text(outcome: Any) -> str:
    output_dir = getattr(outcome, "output_dir", None)
    summary = getattr(outcome, "summary", None)
    if not isinstance(output_dir, Path) or not isinstance(summary, dict):
        return ""

    chunks: list[str] = []
    candidates = summary.get("candidates")
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
    return render_markdown_summary(summary)


def _outcome_summary_text(outcome: Any, fallback: str) -> str:
    output_dir = getattr(outcome, "output_dir", None)
    summary = getattr(outcome, "summary", None)
    if isinstance(output_dir, Path):
        summary_file = output_dir / "run-summary.md"
        if summary_file.exists():
            return summary_file.read_text(encoding="utf-8")
    if isinstance(summary, dict):
        return render_markdown_summary(summary)
    return fallback


def _copy_text_artifacts(run_id: str, artifacts_dir: Path) -> None:
    stored_dir = run_directory(run_id)
    for name in ("manifest.json", "run-summary.json", "run-summary.md"):
        source = artifacts_dir / name
        if source.exists() and source.is_file():
            (stored_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


@results_app.command("list")
def list_results() -> None:
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


@results_app.command("show")
def show_result(run_id: Annotated[str, typer.Argument(help="Run ID to show.")]) -> None:
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


@results_app.command("path")
def result_path(run_id: Annotated[str, typer.Argument(help="Run ID to locate.")]) -> None:
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


@results_app.command("cat")
def cat_result(
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


@app.command()
def clean(
    manifest: Annotated[
        Path | None,
        typer.Argument(help="Manifest file to clean.", metavar="MANIFEST"),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print planned deletions only.")] = False,
    force: Annotated[bool, typer.Option("--force", help="Continue after non-critical errors.")] = False,
    results: Annotated[
        bool,
        typer.Option("--results", help="Also remove stored results under the configured results root."),
    ] = False,
) -> None:
    """Remove only manifest-recorded worktrees and run artifacts."""
    if manifest is None and not results:
        console.print("cleanup failed: MANIFEST is required unless --results is set", style="red")
        raise typer.Exit(2)

    cleanup_results = []
    try:
        if manifest is not None:
            cleanup_results.append(clean_resources(manifest, dry_run=dry_run, force=force))
        if results:
            cleanup_results.append(clean_results(dry_run=dry_run))
    except CleanupSafetyError as exc:
        console.print(f"cleanup safety check failed: {exc}", style="red")
        raise typer.Exit(5) from exc
    except Exception as exc:
        console.print(f"cleanup failed: {exc}", style="red")
        raise typer.Exit(5) from exc

    errors: list[str] = []
    for result in cleanup_results:
        for action in result.actions:
            prefix = "would remove" if dry_run else "removed"
            console.print(f"{prefix} {action.kind}: {action.path}", soft_wrap=True)
        errors.extend(result.errors)
    if errors:
        for error in errors:
            console.print(error, style="red")
        raise typer.Exit(5)
    raise typer.Exit(0)


if __name__ == "__main__":
    app()
