from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_feia.results_store import (
    complete_run_record,
    list_run_metadata,
    read_result_file,
    resolve_results_root,
    result_file_path,
    run_directory,
    start_run_record,
)


def test_results_root_uses_home_default_and_env_override(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("EVAL_FEIA_BASE_DIR", raising=False)
    monkeypatch.delenv("EVAL_FEIA_RESULTS_DIR", raising=False)

    assert resolve_results_root() == (home / ".eval-feia").resolve(strict=False)

    base = tmp_path / "state"
    monkeypatch.setenv("EVAL_FEIA_BASE_DIR", str(base))

    assert resolve_results_root() == base.resolve(strict=False)

    override = tmp_path / "custom-results"
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(override))

    assert resolve_results_root() == override.resolve(strict=False)


def test_run_record_writes_metadata_files_and_append_index(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "results"
    run_id = "20260517-143012-a1b2c3"
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(root))

    start_run_record(
        run_id,
        cwd=tmp_path,
        branch="main",
        label="smoke",
        command="bash",
    )
    complete_run_record(
        run_id,
        status="success",
        exit_code=0,
        output_text="final output\n",
        summary_text="summary\n",
        stdout_text="stdout\n",
        stderr_text="",
    )

    run_dir = run_directory(run_id)
    assert (root / ".eval-feia-results").read_text(encoding="utf-8") == "eval-feia results\n"
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["run_id"] == run_id
    assert metadata["status"] == "success"
    assert metadata["cwd"] == str(tmp_path.resolve(strict=False))
    assert metadata["output_dir"] == str(run_dir)
    assert metadata["branch"] == "main"
    assert metadata["label"] == "smoke"
    assert metadata["command"] == "bash"
    assert metadata["exit_code"] == 0
    assert read_result_file(run_id) == "final output\n"
    assert (run_dir / "summary.txt").read_text(encoding="utf-8") == "summary\n"
    assert (root / "index.jsonl").read_text(encoding="utf-8").count("\n") == 2
    assert list_run_metadata()[0]["status"] == "success"


def test_list_falls_back_to_metadata_when_index_is_damaged(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "results"
    run_id = "20260517-143012-a1b2c3"
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(root))
    start_run_record(run_id, cwd=tmp_path, branch="HEAD", label=None, command=None)
    complete_run_record(
        run_id,
        status="failed",
        exit_code=1,
        output_text="",
        summary_text="failed\n",
        stdout_text="",
        stderr_text="failed\n",
    )
    (root / "index.jsonl").write_text("not json\n", encoding="utf-8")

    records = list_run_metadata()

    assert [record["run_id"] for record in records] == [run_id]
    assert records[0]["status"] == "failed"


def test_result_file_path_rejects_traversal(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "results"
    run_id = "20260517-143012-a1b2c3"
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

    with pytest.raises(ValueError, match="relative path"):
        result_file_path(run_id, "../metadata.json")


def test_results_store_refuses_non_empty_unmarked_root(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "shared"
    root.mkdir()
    (root / "unrelated.txt").write_text("do not own", encoding="utf-8")
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(root))

    with pytest.raises(ValueError, match="non-empty results root"):
        start_run_record("20260517-143012-a1b2c3", cwd=tmp_path, branch="HEAD", label=None, command=None)


def test_results_store_refuses_unexpected_entries_in_marked_root(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "results"
    root.mkdir()
    (root / ".eval-feia-results").write_text("eval-feia results\n", encoding="utf-8")
    (root / "runs").mkdir()
    (root / "unrelated.txt").write_text("do not own", encoding="utf-8")
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(root))

    with pytest.raises(ValueError, match="unexpected entries"):
        start_run_record("20260517-143012-a1b2c3", cwd=tmp_path, branch="HEAD", label=None, command=None)


def test_results_store_refuses_symlink_marker(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "results"
    root.mkdir()
    marker_target = tmp_path / "marker-target"
    marker_target.write_text("eval-feia results\n", encoding="utf-8")
    (root / ".eval-feia-results").symlink_to(marker_target)
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(root))

    with pytest.raises(ValueError, match="marker is invalid"):
        start_run_record("20260517-143012-a1b2c3", cwd=tmp_path, branch="HEAD", label=None, command=None)


def test_results_store_refuses_symlink_run_directory(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "results"
    root.mkdir()
    (root / ".eval-feia-results").write_text("eval-feia results\n", encoding="utf-8")
    (root / "runs").mkdir()
    (root / "runs" / "20260517-143012-a1b2c3").symlink_to(tmp_path)
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(root))

    with pytest.raises(ValueError, match="stored run directory is a symlink"):
        start_run_record("20260517-143012-a1b2c3", cwd=tmp_path, branch="HEAD", label=None, command=None)
