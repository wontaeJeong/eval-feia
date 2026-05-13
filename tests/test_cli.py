# pyright: reportMissingImports=false
from __future__ import annotations

from typer.testing import CliRunner

from eval_feia.cli import app


runner = CliRunner()


def test_placeholder_commands_exist() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ["run", "collect", "fetch", "cleanup", "inspect"]:
        assert command in result.stdout


def test_collect_placeholder() -> None:
    result = runner.invoke(app, ["collect", "--output-dir", "results"])
    assert result.exit_code == 0
    assert "collected" in result.stdout
