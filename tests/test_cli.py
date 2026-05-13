# pyright: reportMissingImports=false
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from eval_feia.cli import app
from eval_feia.reports import write_json


def test_cli_help_lists_required_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("run", "collect", "fetch", "cleanup", "inspect"):
        assert command in result.output


def test_collect_recomputes_summary(tmp_path: Path) -> None:
    batch = tmp_path / "batch"
    run_dir = batch / "runs" / "run-001"
    run_dir.mkdir(parents=True)
    write_json(batch / "manifest.json", {"batch_id": "batch", "opencode_version": "1.4.6", "runs": []})
    write_json(
        run_dir / "run.json",
        {
            "batch_id": "batch",
            "run_id": "run-001",
            "status": "completed",
            "failure_class": "none",
            "worktree": {"path": "/tmp/worktree"},
            "server_info": {"port": 4096},
            "metrics": {"task_success": True, "server_restart_count": 0},
            "validation": {"validation_passed": True},
        },
    )
    result = CliRunner().invoke(app, ["collect", str(batch)], catch_exceptions=False)
    assert result.exit_code == 0
    summary = json.loads((batch / "summary.json").read_text(encoding="utf-8"))
    assert summary["total_runs"] == 1
