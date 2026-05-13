# pyright: reportMissingImports=false
from __future__ import annotations

import io
import json
from pathlib import Path

from eval_feia.cleanup import CleanupError, cleanup_manifest
from eval_feia.models import BatchManifest, now_iso, to_jsonable
from eval_feia.reports import write_json, write_manifest, write_run_record
from eval_feia.models import RunRecord
from eval_feia.worktree import WorktreeManager


def test_worktree_path_output_and_manifest_record(git_repo: Path, tmp_path: Path) -> None:
    stream = io.StringIO()
    manager = WorktreeManager(git_repo, tmp_path / "tmp")
    info = manager.create_run_worktree("batch-1", "run-001", stream=stream)
    assert Path(info.path).is_absolute()
    assert f"[run-001] worktree: {info.path}" in stream.getvalue()

    manifest = BatchManifest(
        batch_id="batch-1",
        created_at=now_iso(),
        repo=str(git_repo),
        base_ref="HEAD",
        base_commit=info.base_commit,
        opencode_version="1.4.6",
        runs=[{"run_id": "run-001", "worktree": to_jsonable(info)}],
    )
    manifest_path = tmp_path / "results" / "manifest.json"
    write_manifest(manifest_path, manifest)
    run = RunRecord(run_id="run-001", batch_id="batch-1", worktree=info)
    write_run_record(tmp_path / "results" / "runs" / "run-001", run)

    assert json.loads(manifest_path.read_text())["runs"][0]["worktree"]["path"] == info.path
    run_json = json.loads((tmp_path / "results" / "runs" / "run-001" / "run.json").read_text())
    assert run_json["worktree"]["path"] == info.path


def test_jsonl_worktree_event_and_distinct_paths(git_repo: Path, tmp_path: Path) -> None:
    stream = io.StringIO()
    manager = WorktreeManager(git_repo, tmp_path / "tmp")
    first = manager.create_run_worktree("batch-1", "run-001", stream=stream, json_mode=True)
    second = manager.create_run_worktree("batch-1", "run-002", stream=stream, json_mode=True)
    assert first.path != second.path
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert lines[0]["type"] == "worktree_created"
    assert lines[0]["path"] == first.path
    assert lines[1]["path"] == second.path


def test_cleanup_only_manifest_owned_paths(tmp_path: Path) -> None:
    root = tmp_path / "root"
    run_root = root / "batch-1" / "run-001"
    owned = run_root / "worktree"
    other = tmp_path / "other"
    owned.mkdir(parents=True)
    (run_root / "home").mkdir()
    (run_root / "tmp").mkdir()
    other.mkdir()
    (owned / "file.txt").write_text("owned")
    (owned / ".eval-feia-worktree").write_text("owned")
    (other / "file.txt").write_text("other")
    manifest = tmp_path / "manifest.json"
    write_json(manifest, {"worktree_root": str(root), "runs": [{"run_id": "run-001", "worktree": {"path": str(owned)}}]})
    removed = cleanup_manifest(manifest)
    assert removed == [run_root.resolve()]
    assert not run_root.exists()
    assert other.exists()


def test_cleanup_rejects_paths_outside_worktree_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside" / "worktree"
    outside.mkdir(parents=True)
    (outside / ".eval-feia-worktree").write_text("owned")
    manifest = tmp_path / "manifest.json"
    write_json(manifest, {"worktree_root": str(root), "runs": [{"run_id": "run-001", "worktree": {"path": str(outside)}}]})
    try:
        cleanup_manifest(manifest)
    except CleanupError as exc:
        assert "outside worktree_root" in str(exc)
    else:
        raise AssertionError("cleanup accepted a path outside worktree_root")
