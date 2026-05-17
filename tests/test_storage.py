from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from eval_feia.cli import app
from eval_feia.storage import (
    StorageError,
    backfill_from_output_dir,
    create_run,
    default_db_path,
    init_db,
    list_runs,
    update_run,
)


def test_init_db_creates_runs_table(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "eval-feia.sqlite3"

    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert "runs" in tables
    assert "run_events" in tables
    assert user_version == 1


def test_init_db_rejects_symlink_path(tmp_path: Path) -> None:
    link_path = tmp_path / "linked.sqlite3"
    link_path.symlink_to(tmp_path / "target.sqlite3")

    with pytest.raises(StorageError, match="symlink"):
        init_db(link_path)


def test_create_update_and_list_run(tmp_path: Path) -> None:
    db_path = tmp_path / "eval-feia.sqlite3"
    output_dir = tmp_path / "runs" / "run-1"

    create_run(
        db_path,
        run_id="run-1",
        status="running",
        created_at="2026-01-01T00:00:00+00:00",
        started_at="2026-01-01T00:00:00+00:00",
        cwd=tmp_path,
        repo_root=tmp_path / "repo",
        branch="main",
        label="smoke",
        command="bash",
        prompt="hello",
        output_dir=output_dir,
    )
    update_run(
        db_path,
        "run-1",
        status="success",
        ended_at="2026-01-01T00:00:02+00:00",
        duration_ms=2000,
        exit_code=0,
        summary_path=output_dir / "run-summary.json",
    )

    rows = list_runs(db_path)

    assert len(rows) == 1
    assert rows[0]["id"] == "run-1"
    assert rows[0]["status"] == "success"
    assert rows[0]["branch"] == "main"
    assert rows[0]["label"] == "smoke"
    assert rows[0]["duration_ms"] == 2000
    assert rows[0]["summary_path"] == str((output_dir / "run-summary.json").resolve(strict=False))


def test_list_runs_orders_latest_first_and_filters(tmp_path: Path) -> None:
    db_path = tmp_path / "eval-feia.sqlite3"
    create_run(
        db_path,
        run_id="old",
        status="failed",
        created_at="2026-01-01T00:00:00+00:00",
        started_at="2026-01-01T00:00:00+00:00",
        branch="main",
        label="nightly",
    )
    create_run(
        db_path,
        run_id="new",
        status="success",
        created_at="2026-01-02T00:00:00+00:00",
        started_at="2026-01-02T00:00:00+00:00",
        branch="feature",
        label="smoke",
    )

    assert [row["id"] for row in list_runs(db_path)] == ["new", "old"]
    assert [row["id"] for row in list_runs(db_path, status="success")] == ["new"]
    assert [row["id"] for row in list_runs(db_path, branch="main")] == ["old"]
    assert [row["id"] for row in list_runs(db_path, label="smoke")] == ["new"]


def test_backfill_from_output_dir_is_idempotent(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    run_dir = output_root / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "created_at": "2026-01-01T00:00:00+00:00",
                "label": "legacy",
                "repo": {"path": str(tmp_path / "repo"), "base_ref": "main", "base_sha": "abc"},
                "output_dir": str(run_dir),
                "worktree_root": str(tmp_path / "worktrees" / "run-1"),
                "candidates": [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run-summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "label": "legacy",
                "repo": {"path": str(tmp_path / "repo"), "base_ref": "main", "base_sha": "abc"},
                "output_dir": str(run_dir),
                "passed": True,
                "candidates": [
                    {
                        "started_at": "2026-01-01T00:00:01+00:00",
                        "completed_at": "2026-01-01T00:00:03+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "eval-feia.sqlite3"

    assert backfill_from_output_dir(db_path, output_root) == 1
    assert backfill_from_output_dir(db_path, output_root) == 0

    rows = list_runs(db_path)
    assert len(rows) == 1
    assert rows[0]["id"] == "run-1"
    assert rows[0]["status"] == "success"
    assert rows[0]["output_dir"] == str(run_dir.resolve(strict=False))
    assert rows[0]["duration_ms"] == 2000


def test_cli_list_json_outputs_valid_json(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "eval-feia.sqlite3"
    monkeypatch.setenv("EVAL_FEIA_DB_PATH", str(db_path))
    create_run(
        db_path,
        run_id="json-run",
        status="success",
        branch="main",
        output_dir=tmp_path / "runs" / "json-run",
    )

    result = CliRunner().invoke(app, ["list-run-artifacts", "--json"], color=False)

    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert rows[0]["id"] == "json-run"
    assert rows[0]["status"] == "success"


def test_default_db_path_uses_environment_override(monkeypatch, tmp_path: Path) -> None:
    override = tmp_path / "custom.sqlite3"
    monkeypatch.setenv("EVAL_FEIA_DB_PATH", str(override))

    assert default_db_path(tmp_path / "runs") == override.resolve(strict=False)
