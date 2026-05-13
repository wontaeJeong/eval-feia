from __future__ import annotations

from pathlib import Path

import pytest

from eval_feia.cleanup import MARKER_FILE, ROOT_MARKER_FILE
from eval_feia.cleanup import cleanup_from_manifest
from eval_feia.reports import write_json
from eval_feia.worktree import create_worktree, resolve_base_commit


def test_worktree_creation_returns_absolute_path_and_cleanup_is_manifest_based(git_repo: Path, tmp_path: Path) -> None:
    base_commit = resolve_base_commit(git_repo, "HEAD")
    worktree_path = tmp_path / "owned" / "worktree"
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    info = create_worktree(git_repo, worktree_path, "HEAD", base_commit)
    assert Path(info.path).is_absolute()
    assert Path(info.path).exists()
    manifest = tmp_path / "manifest.json"
    (tmp_path / ROOT_MARKER_FILE).write_text("batch\n", encoding="utf-8")
    (tmp_path / "owned" / MARKER_FILE).write_text("run-001\n", encoding="utf-8")
    write_json(
        manifest,
        {
            "repo": str(git_repo),
            "worktree_root": str(tmp_path),
            "runs": [{"run_id": "run-001", "worktree": {"path": info.path}, "temp_run_dir": str(tmp_path / "owned")}],
        },
    )
    result = cleanup_from_manifest(manifest)
    assert result["ok"] is True
    assert not (tmp_path / "owned").exists()
    assert unrelated.exists()


def test_cleanup_refuses_paths_outside_manifest_root(git_repo: Path, tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-eval-feia-delete-me"
    safe_root = tmp_path / "safe-root"
    safe_root.mkdir()
    (safe_root / ROOT_MARKER_FILE).write_text("batch\n", encoding="utf-8")
    outside.mkdir(exist_ok=True)
    (outside / MARKER_FILE).write_text("run-999\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    write_json(
        manifest,
        {
            "repo": str(git_repo),
            "worktree_root": str(safe_root),
            "runs": [{"run_id": "run-999", "worktree": {"path": str(outside / "worktree")}, "temp_run_dir": str(outside)}],
        },
    )
    result = cleanup_from_manifest(manifest)
    assert result["ok"] is False
    assert str(outside) in result["refused"]
    assert outside.exists()
    (outside / MARKER_FILE).unlink()
    outside.rmdir()


def test_cleanup_rejects_dangerous_manifest_root(git_repo: Path, tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    write_json(manifest, {"repo": str(git_repo), "worktree_root": "/", "runs": []})
    with pytest.raises(ValueError):
        cleanup_from_manifest(manifest)


def test_cleanup_recovers_temp_run_dir_from_run_json(git_repo: Path, tmp_path: Path) -> None:
    batch_dir = tmp_path / "batch"
    root = tmp_path / "root"
    temp_run_dir = root / "run-001"
    worktree_path = temp_run_dir / "worktree"
    (root).mkdir()
    temp_run_dir.mkdir()
    (root / ROOT_MARKER_FILE).write_text("batch\n", encoding="utf-8")
    (temp_run_dir / MARKER_FILE).write_text("run-001\n", encoding="utf-8")
    base_commit = resolve_base_commit(git_repo, "HEAD")
    info = create_worktree(git_repo, worktree_path, "HEAD", base_commit)
    run_dir = batch_dir / "runs" / "run-001"
    run_dir.mkdir(parents=True)
    write_json(run_dir / "run.json", {"run_id": "run-001", "worktree": {"path": info.path}, "temp_run_dir": str(temp_run_dir)})
    manifest = batch_dir / "manifest.json"
    write_json(manifest, {"repo": str(git_repo), "worktree_root": str(root), "runs": []})
    result = cleanup_from_manifest(manifest)
    assert result["ok"] is True
    assert not temp_run_dir.exists()
