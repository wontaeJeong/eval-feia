from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .clean import clean_resources
from .config import ConfigOverrides, load_config
from .errors import CleanupSafetyError, ConfigError, EvalFeiaError, GitError, HealthError
from .runner import run_evaluation


app = typer.Typer(add_completion=False, help="REST-only opencode worktree evaluator.")
console = Console()


@app.command()
def run(
    config: Annotated[Path | None, typer.Option("--config", help="Path to eval-feia config file.")] = None,
    server_url: Annotated[str | None, typer.Option("--server-url", help="opencode server URL.")] = None,
    repo: Annotated[Path | None, typer.Option("--repo", help="Git repository path.")] = None,
    base_ref: Annotated[str | None, typer.Option("--base-ref", help="Base git ref.")] = None,
    worktrees: Annotated[int | None, typer.Option("--worktrees", help="Number of candidates.")] = None,
    prompt_file: Annotated[Path | None, typer.Option("--prompt-file", help="Prompt file.")] = None,
    prompt: Annotated[str | None, typer.Option("--prompt", help="Inline prompt text.")] = None,
    branch_name: Annotated[
        str | None,
        typer.Option("--branch-name", help="Default branch name for a single eval/candidate."),
    ] = None,
    label: Annotated[
        str | None,
        typer.Option("--label", help="Default human-readable eval label."),
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
        eval_config = load_config(
            config,
            ConfigOverrides(
                server_url=server_url,
                repo=repo,
                base_ref=base_ref,
                worktrees=worktrees,
                prompt_file=prompt_file,
                prompt=prompt,
                branch_name=branch_name,
                label=label,
                command=command,
                output_dir=output_dir,
            ),
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


@app.command()
def clean(
    manifest: Annotated[Path, typer.Option("--manifest", help="Manifest file to clean.")],
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
