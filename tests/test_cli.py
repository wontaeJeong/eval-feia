from __future__ import annotations

from typer.testing import CliRunner

from eval_feia.cli import app


def test_run_help_lists_command_option() -> None:
    result = CliRunner().invoke(app, ["run", "--help"], color=False)

    assert result.exit_code == 0
    assert "--command" in result.output
    assert "Run an opencode slash command" in result.output
    assert "command arguments" in result.output
