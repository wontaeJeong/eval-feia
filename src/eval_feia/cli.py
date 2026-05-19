from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, cast

import typer
from rich.console import Console

from .clean import CleanupResult, clean_resources, clean_results
from .config import EvalConfig, build_config
from .errors import CleanupSafetyError, ConfigError, EvalFeiaError, GitError, HealthError
from .listing import list_saved_runs, print_saved_runs, saved_runs_json
from .paths import BASE_DIR_ENV, output_root_for_base, results_dir_for_run
from .results_store import (
    complete_run_record,
    load_metadata,
    read_result_file,
    run_directory,
    start_run_record,
)
from .records import RunSummary
from .runner import RunOutcome, generate_run_id, run_evaluation
from .summary import render_markdown_summary


app = typer.Typer(add_completion=False, help="REST-only opencode worktree evaluator.")
results_app = typer.Typer(add_completion=False, help="Inspect stored run results.")
console = Console()
VALID_LIST_STATUSES = {"pending", "running", "success", "failed", "cancelled", "unknown"}


@app.command("run")
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
    progress: Annotated[
        bool,
        typer.Option(
            "--progress/--no-progress",
            help="Show live progress logs, including opencode event stream updates.",
        ),
    ] = True,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", help="Hide progress logs while keeping final output."),
    ] = False,
    base_dir: Annotated[
        Path | None,
        typer.Option(
            "--base-dir",
            help=(
                "Eval-feia base directory. Runs, worktrees, and results are derived "
                f"from it. Overrides {BASE_DIR_ENV}."
            ),
        ),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Generated run output root for run artifacts.",
        ),
    ] = None,
) -> None:
    """Create worktrees, execute opencode sessions, collect results, and summarize."""
    if base_dir is not None and output_dir is not None:
        console.print("--base-dir and --output-dir cannot be used together", style="red")
        raise typer.Exit(2)
    run_id = generate_run_id()
    results_root = _results_root_for_base_dir(run_id, base_dir)
    stored_output_dir = run_directory(run_id, root=results_root)
    run_console = Console(record=True)
    run_console.print(f"Run ID: {run_id}", markup=False)
    run_console.print(f"Output directory: {stored_output_dir}", markup=False, soft_wrap=True)
    start_run_record(
        run_id,
        cwd=Path.cwd(),
        branch=branch or "HEAD",
        label=label,
        command=command,
        root=results_root,
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
            progress=progress and not quiet,
            base_dir=base_dir,
            output_dir=output_dir,
        )
        outcome = run_evaluation(eval_config, console=run_console, run_id=run_id)
    except ConfigError as exc:
        message = f"configuration error: {exc}"
        run_console.print(message, style="red")
        _finish_failed_cli_run(run_id, run_console, exc, message, exit_code=2, results_root=results_root)
        raise typer.Exit(2) from exc
    except HealthError as exc:
        message = f"opencode preflight failed: {exc}"
        run_console.print(message, style="red")
        _finish_failed_cli_run(run_id, run_console, exc, message, exit_code=3, results_root=results_root)
        raise typer.Exit(3) from exc
    except GitError as exc:
        message = f"git worktree setup failed: {exc}"
        run_console.print(message, style="red")
        _finish_failed_cli_run(run_id, run_console, exc, message, exit_code=4, results_root=results_root)
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
            results_root=results_root,
        )
        raise typer.Exit(130) from exc
    except EvalFeiaError as exc:
        message = f"eval-feia failed: {exc}"
        run_console.print(message, style="red")
        _finish_failed_cli_run(run_id, run_console, exc, message, exit_code=1, results_root=results_root)
        raise typer.Exit(1) from exc
    exit_code = 0 if outcome.passed else 1
    _finish_completed_cli_run(run_id, run_console, outcome, exit_code=exit_code, results_root=results_root)
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
    progress: bool | None,
    base_dir: Path | None,
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
        progress=progress,
        base_root=base_dir,
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


def _results_root_for_base_dir(run_id: str, base_dir: Path | None) -> Path | None:
    if base_dir is None:
        return None
    return results_dir_for_run(run_id, base_dir).expanduser().resolve(strict=False)


def _list_run_artifacts_command(
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Show only the most recent N saved runs."),
    ] = None,
    base_dir: Annotated[
        Path | None,
        typer.Option("--base-dir", help="Eval-feia base directory to inspect."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Generated run artifact root to inspect."),
    ] = None,
    status: Annotated[str | None, typer.Option("--status", help="Filter by run status.")] = None,
    branch: Annotated[str | None, typer.Option("--branch", help="Filter by branch/base ref.")] = None,
    label: Annotated[str | None, typer.Option("--label", help="Filter by run label.")] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print saved runs as a JSON array."),
    ] = False,
) -> None:
    """List generated run artifacts and stored result metadata."""
    if limit is not None and limit < 1:
        console.print("--limit must be greater than zero", style="red")
        raise typer.Exit(2)
    if status is not None and status not in VALID_LIST_STATUSES:
        console.print(
            "invalid --status; expected one of " + ", ".join(sorted(VALID_LIST_STATUSES)),
            style="red",
        )
        raise typer.Exit(2)
    if base_dir is not None and output_dir is not None:
        console.print("--base-dir and --output-dir cannot be used together", style="red")
        raise typer.Exit(2)
    runs = list_saved_runs(
        output_root=_output_root_for_list(base_dir=base_dir, output_dir=output_dir),
        limit=limit,
        status=status,
        branch=branch,
        label=label,
        include_results=output_dir is None,
        include_configured_results=base_dir is None and output_dir is None,
    )
    if json_output:
        typer.echo(saved_runs_json(runs))
        raise typer.Exit(0)
    print_saved_runs(console, runs)
    raise typer.Exit(0)


def _output_root_for_list(*, base_dir: Path | None, output_dir: Path | None) -> Path:
    if output_dir is not None:
        return output_dir.expanduser().resolve(strict=False)
    if base_dir is not None:
        return output_root_for_base(base_dir).expanduser().resolve(strict=False)
    return output_root_for_base().expanduser().resolve(strict=False)


app.command("list")(_list_run_artifacts_command)


def _finish_completed_cli_run(
    run_id: str,
    run_console: Console,
    outcome: RunOutcome,
    *,
    exit_code: int,
    results_root: Path | None = None,
) -> None:
    output_text = _outcome_output_text(outcome)
    summary_text = _outcome_summary_text(outcome, output_text)
    status = "success" if exit_code == 0 else "failed"
    extra: dict[str, Any] = {}
    artifacts_dir = getattr(outcome, "output_dir", None)
    if isinstance(artifacts_dir, Path):
        extra["artifacts_dir"] = str(artifacts_dir)
        _copy_text_artifacts(run_id, artifacts_dir, results_root=results_root)
    complete_run_record(
        run_id,
        status=status,
        exit_code=exit_code,
        output_text=output_text,
        summary_text=summary_text,
        stdout_text=run_console.export_text(),
        stderr_text="",
        extra=extra,
        root=results_root,
    )


def _finish_failed_cli_run(
    run_id: str,
    run_console: Console,
    exc: EvalFeiaError | None,
    message: str,
    *,
    exit_code: int,
    kind: str | None = None,
    results_root: Path | None = None,
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
        root=results_root,
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


def _copy_text_artifacts(run_id: str, artifacts_dir: Path, *, results_root: Path | None = None) -> None:
    stored_dir = run_directory(run_id, root=results_root)
    for name in ("manifest.json", "run-summary.json", "run-summary.md"):
        source = artifacts_dir / name
        if source.exists() and source.is_file():
            (stored_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


@results_app.command("show")
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


@results_app.command("path")
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


@results_app.command("file")
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
        text = read_result_file(run_id, "summary.txt")
    except FileNotFoundError:
        text = read_result_file(run_id, "output.txt")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n..."


def _raise_results_error(exc: Exception) -> None:
    console.print(f"results error: {exc}", style="red")
    raise typer.Exit(1) from exc


@app.command("clean")
def clean(
    manifest: Annotated[
        Path | None,
        typer.Argument(help="Manifest file for generated run artifacts.", metavar="MANIFEST"),
    ] = None,
    base_dir: Annotated[
        Path | None,
        typer.Option("--base-dir", help="Eval-feia base directory used with --results."),
    ] = None,
    results: Annotated[
        bool,
        typer.Option("--results", help="Remove the configured stored-results history root."),
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print planned deletions only.")] = False,
    force: Annotated[bool, typer.Option("--force", help="Continue after non-critical errors.")] = False,
) -> None:
    """Remove generated run artifacts, or stored results with --results."""
    if results:
        if manifest is not None:
            console.print("MANIFEST cannot be used with --results", style="red")
            raise typer.Exit(2)
        if force:
            console.print("--force applies only to manifest cleanup", style="red")
            raise typer.Exit(2)
        _clean_stored_results(base_dir=base_dir, dry_run=dry_run)
        return

    if manifest is None:
        console.print("MANIFEST is required unless --results is set", style="red")
        raise typer.Exit(2)
    if base_dir is not None:
        console.print("--base-dir applies only with --results", style="red")
        raise typer.Exit(2)

    try:
        cleanup_result = clean_resources(
            manifest,
            dry_run=dry_run,
            force=force,
        )
    except CleanupSafetyError as exc:
        console.print(f"cleanup safety check failed: {exc}", style="red")
        raise typer.Exit(5) from exc
    except Exception as exc:
        console.print(f"cleanup failed: {exc}", style="red")
        raise typer.Exit(5) from exc
    _print_cleanup_result(cleanup_result, dry_run=dry_run)


def _clean_stored_results(*, base_dir: Path | None, dry_run: bool) -> None:
    try:
        cleanup_result = clean_results(_results_base_for_cleanup(base_dir), dry_run=dry_run)
    except CleanupSafetyError as exc:
        console.print(f"cleanup safety check failed: {exc}", style="red")
        raise typer.Exit(5) from exc
    except Exception as exc:
        console.print(f"cleanup failed: {exc}", style="red")
        raise typer.Exit(5) from exc
    _print_cleanup_result(cleanup_result, dry_run=dry_run)


def _results_base_for_cleanup(base_dir: Path | None) -> Path | None:
    if base_dir is None:
        return None
    return output_root_for_base(base_dir).expanduser().resolve(strict=False)


app.add_typer(results_app, name="results")


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
