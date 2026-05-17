from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from eval_feia.cli import app
from eval_feia.results_store import complete_run_record, run_directory, start_run_record


def test_run_help_lists_command_option() -> None:
    result = CliRunner().invoke(app, ["run", "--help"], color=False)

    assert result.exit_code == 0
    assert "--command" in result.output
    assert "Run an opencode slash command" in result.output
    assert "arguments" in result.output
    assert "--branch" in result.output
    assert "--attempts" in result.output
    assert "--repo" in result.output
    assert "--config" not in result.output
    assert "--base-ref" not in result.output
    assert "--worktrees" not in result.output
    assert "--branch-name" not in result.output
    assert "http://127.0.0.1:4096" in result.output
    assert "HEAD" in result.output


def test_run_accepts_canonical_args_and_prompt_argument(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    run_id = "20260517-143012-a1b2c3"
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(tmp_path / "stored-results"))
    monkeypatch.setattr("eval_feia.cli.generate_run_id", lambda: run_id)

    def fake_run_evaluation(config, *, console, run_id):
        captured["config"] = config
        captured["console"] = console
        captured["run_id"] = run_id

        class Outcome:
            passed = True
            output_dir = tmp_path / "artifacts" / run_id
            summary = {
                "run_id": run_id,
                "label": None,
                "server": {"url": "http://opencode.test"},
                "opencode_version": "fake",
                "repo": {"path": str(tmp_path), "base_ref": "main", "base_sha": "abc123"},
                "output_dir": str(output_dir),
                "passed": True,
                "health": {},
                "candidates": [],
            }

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
    assert captured["run_id"] == run_id
    assert f"Run ID: {run_id}" in result.output
    assert "Output directory:" in result.output
    metadata = json.loads((run_directory(run_id) / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "success"
    assert metadata["exit_code"] == 0


def test_run_rejects_removed_config_and_alias_options() -> None:
    for option in ("--config", "--base-ref", "--worktrees", "--prompt", "--branch-name"):
        result = CliRunner().invoke(app, ["run", "hello inline", option, "value"], color=False)

        assert result.exit_code == 2


def test_run_rejects_prompt_argument_with_prompt_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(tmp_path / "stored-results"))
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
    assert "--results" in result.output
    assert "--manifest" not in result.output


def test_results_commands_list_show_path_and_cat(monkeypatch, tmp_path: Path) -> None:
    run_id = "20260517-143012-a1b2c3"
    root = tmp_path / "results"
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(root))
    start_run_record(run_id, cwd=tmp_path, branch="main", label="demo", command="bash")
    complete_run_record(
        run_id,
        status="success",
        exit_code=0,
        output_text="final output\n",
        summary_text="quick summary\n",
        stdout_text="stdout\n",
        stderr_text="",
    )

    listed = CliRunner().invoke(app, ["results", "list"], color=False)
    assert listed.exit_code == 0
    assert "RUN_ID" in listed.output
    assert "STATUS" in listed.output
    assert run_id in listed.output
    assert "success" in listed.output

    shown = CliRunner().invoke(app, ["results", "show", run_id], color=False)
    assert shown.exit_code == 0
    assert "run_id: 20260517-143012-a1b2c3" in shown.output
    assert "status: success" in shown.output
    assert "quick summary" in shown.output

    path = CliRunner().invoke(app, ["results", "path", run_id], color=False)
    assert path.exit_code == 0
    assert path.output == f"{run_directory(run_id)}\n"

    output = CliRunner().invoke(app, ["results", "cat", run_id], color=False)
    assert output.exit_code == 0
    assert output.output == "final output\n"

    metadata = CliRunner().invoke(app, ["results", "cat", run_id, "metadata.json"], color=False)
    assert metadata.exit_code == 0
    assert '"run_id": "20260517-143012-a1b2c3"' in metadata.output


def test_clean_results_option_removes_configured_results_root(monkeypatch, tmp_path: Path) -> None:
    run_id = "20260517-143012-a1b2c3"
    root = tmp_path / "results"
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(root))
    start_run_record(run_id, cwd=tmp_path, branch="HEAD", label=None, command=None)
    complete_run_record(
        run_id,
        status="success",
        exit_code=0,
        output_text="ok\n",
        summary_text="ok\n",
        stdout_text="",
        stderr_text="",
    )

    dry_run = CliRunner().invoke(app, ["clean", "--results", "--dry-run"], color=False)

    assert dry_run.exit_code == 0
    assert f"would remove results: {root.resolve(strict=False)}" in dry_run.output
    assert root.exists()

    cleaned = CliRunner().invoke(app, ["clean", "--results"], color=False)

    assert cleaned.exit_code == 0
    assert f"removed results: {root.resolve(strict=False)}" in cleaned.output
    assert not root.exists()
