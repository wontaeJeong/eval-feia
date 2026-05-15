from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .clean import clean_resources
from .config import EvalConfig, build_config
from .errors import CleanupSafetyError, ConfigError, EvalFeiaError, GitError, HealthError
from .runner import run_evaluation


app = typer.Typer(add_completion=False, help="REST-only opencode worktree evaluator.")
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
) -> None:
    """Remove only manifest-recorded worktrees and run artifacts."""
    try:
        result = clean_resources(manifest, dry_run=dry_run, force=force)
    except CleanupSafetyError as exc:
        console.print(f"cleanup safety check failed: {exc}", style="red")
        raise typer.Exit(5) from exc
    except Exception as exc:
        console.print(f"cleanup failed: {exc}", style="red")
        raise typer.Exit(5) from exc

    for action in result.actions:
        prefix = "would remove" if dry_run else "removed"
        console.print(f"{prefix} {action.kind}: {action.path}")
    if result.errors:
        for error in result.errors:
            console.print(error, style="red")
        raise typer.Exit(5)
    raise typer.Exit(0)


if __name__ == "__main__":
    app()
