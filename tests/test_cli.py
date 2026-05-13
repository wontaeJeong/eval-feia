# pyright: reportMissingImports=false
from __future__ import annotations

from typer.testing import CliRunner

from eval_feia.cli import app


def test_cli_lists_required_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ["run", "collect", "fetch", "cleanup", "inspect"]:
        assert command in result.output


def test_run_help_lists_required_options() -> None:
    result = CliRunner().invoke(app, ["run", "--help"], env={"COLUMNS": "220"})
    assert result.exit_code == 0
    for option in ["--repo", "--count", "--concurrency", "--prompt", "--prompt-file", "--skill", "--branch", "--worktree-root", "--output-dir", "--base-port", "--opencode-version", "--provider", "--model", "--cwd-check", "--restart-on-mismatch", "--json"]:
        assert option in result.output
