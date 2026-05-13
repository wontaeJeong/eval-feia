# pyright: reportMissingImports=false
from __future__ import annotations

import json

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


def test_collect_recomputes_summary_files(tmp_path) -> None:
    batch = tmp_path / "batch"
    run_dir = batch / "runs" / "run-001"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "batch_id": "batch",
                "run_id": "run-001",
                "status": "completed",
                "failure_class": "none",
                "worktree": {"path": "/tmp/worktree"},
                "server_info": {"requested_version": "1.4.6", "port": 4096},
                "metrics": {"task_success": True},
                "validation": {"validation_passed": True},
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["collect", str(batch)])
    assert result.exit_code == 0
    assert (batch / "summary.json").exists()
    assert (batch / "summary.csv").exists()
