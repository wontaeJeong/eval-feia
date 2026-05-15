from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from eval_feia.cli import app


def test_run_help_lists_command_option() -> None:
    result = CliRunner().invoke(app, ["run", "--help"], color=False)

    assert result.exit_code == 0
    assert "--command" in result.output
    assert "Run an opencode slash command" in result.output
    assert "arguments" in result.output
    assert "--branch" in result.output
    assert "--attempts" in result.output
    assert "--config" not in result.output
    assert "--base-ref" not in result.output
    assert "--worktrees" not in result.output
    assert "--branch-name" not in result.output
    assert "http://127.0.0.1:4096" in result.output
    assert "HEAD" in result.output


def test_run_accepts_canonical_args_and_prompt_argument(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_run_evaluation(config, *, console):
        captured["config"] = config
        captured["console"] = console

        class Outcome:
            passed = True

        return Outcome()

    monkeypatch.setattr("eval_feia.cli.run_evaluation", fake_run_evaluation)

    result = CliRunner().invoke(
        app,
        [
            "run",
            "hello inline",
            "--repo",
            str(tmp_path),
            "--branch",
            "main",
            "--attempts",
            "3",
        ],
        color=False,
    )

    assert result.exit_code == 0
    assert captured["config"].run.prompt == "hello inline"
    assert captured["config"].repo.base_ref == "main"
    assert captured["config"].run.candidates == 3


def test_run_rejects_removed_config_and_alias_options() -> None:
    for option in ("--config", "--base-ref", "--worktrees", "--prompt", "--branch-name"):
        result = CliRunner().invoke(app, ["run", "hello inline", option, "value"], color=False)

        assert result.exit_code == 2


def test_run_rejects_prompt_argument_with_prompt_file(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("hello from file", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["run", "hello inline", "--prompt-file", str(prompt_file)],
        color=False,
    )

    assert result.exit_code == 2
    assert "provide only one prompt source" in result.output


def test_clean_manifest_is_positional_argument() -> None:
    result = CliRunner().invoke(app, ["clean", "--help"], color=False)

    assert result.exit_code == 0
    assert "MANIFEST" in result.output
    assert "--manifest" not in result.output
