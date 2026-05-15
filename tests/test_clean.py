from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from eval_feia.clean import clean_resources, plan_cleanup
from eval_feia.errors import CleanupSafetyError
from eval_feia.git_worktree import GitWorktreeManager
from eval_feia.manifest import (
    CandidateManifestRecord,
    Manifest,
    RepoRecord,
    ServerRecord,
    utc_now_iso,
    write_manifest,
)


def test_clean_dry_run_does_not_delete_and_clean_removes_only_manifest_paths(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest.output_dir.mkdir(parents=True)
    manifest.worktree_root.mkdir(parents=True)
    candidate = manifest.candidates[0]
    candidate.worktree_path.mkdir(parents=True)
    candidate.result_dir.mkdir(parents=True)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    manifest_path = write_manifest(manifest)

    dry = clean_resources(manifest_path, dry_run=True, use_git=False)
    assert dry.dry_run is True
    assert candidate.worktree_path.exists()
    assert manifest.output_dir.exists()

    result = clean_resources(manifest_path, dry_run=False, use_git=False)
    assert result.errors == []
    assert not candidate.worktree_path.exists()
    assert not manifest.output_dir.exists()
    assert unrelated.exists()


def test_clean_refuses_repo_root_and_home_like_unsafe_paths(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest.output_dir = manifest.repo.path
    with pytest.raises(CleanupSafetyError):
        plan_cleanup(manifest)


def test_clean_refuses_manifest_outside_output_dir(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest.output_dir.mkdir(parents=True)
    manifest.worktree_root.mkdir(parents=True)
    manifest_path = write_manifest(manifest, tmp_path / "manifest.json")

    with pytest.raises(CleanupSafetyError, match="output_dir/manifest.json"):
        clean_resources(manifest_path, dry_run=True, use_git=False)


def test_clean_refuses_candidate_worktree_outside_worktree_root(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest.output_dir.mkdir(parents=True)
    manifest.worktree_root.mkdir(parents=True)
    manifest.candidates[0].worktree_path = tmp_path / "outside-worktree"
    manifest_path = write_manifest(manifest)

    with pytest.raises(CleanupSafetyError, match="outside generated roots"):
        clean_resources(manifest_path, dry_run=True, use_git=False)


def test_clean_refuses_candidate_result_dir_outside_output_dir(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest.output_dir.mkdir(parents=True)
    manifest.worktree_root.mkdir(parents=True)
    manifest.candidates[0].result_dir = tmp_path / "outside-result"
    manifest_path = write_manifest(manifest)

    with pytest.raises(CleanupSafetyError, match="outside generated roots"):
        clean_resources(manifest_path, dry_run=True, use_git=False)


def test_clean_refuses_symlink_cleanup_target(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest.output_dir.mkdir(parents=True)
    manifest.worktree_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    manifest.candidates[0].worktree_path.symlink_to(outside, target_is_directory=True)
    manifest_path = write_manifest(manifest)

    with pytest.raises(CleanupSafetyError, match="symlink"):
        clean_resources(manifest_path, dry_run=True, use_git=False)


def test_clean_removes_dirty_git_worktree_without_force(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = GitWorktreeManager(repo)
    manifest = _manifest_for_repo(repo)
    worktree = manager.create_branch_worktree(
        manifest.worktree_root,
        "cand-001",
        "HEAD",
        "eval/run-1/cand-001",
    )
    manifest.candidates[0].worktree_path = worktree.path
    worktree.path.joinpath("dirty.txt").write_text("dirty\n", encoding="utf-8")
    manifest.candidates[0].result_dir.mkdir(parents=True)
    manifest_path = write_manifest(manifest)

    result = clean_resources(manifest_path)

    assert result.errors == []
    assert not worktree.path.exists()
    assert not manifest.output_dir.exists()


def _manifest(tmp_path: Path) -> Manifest:
    repo = (tmp_path / "repo").resolve()
    repo.mkdir()
    return _manifest_for_repo(repo)


def _manifest_for_repo(repo: Path) -> Manifest:
    output = (repo / ".eval-feia" / "runs" / "run-1").resolve()
    worktree_root = (repo / ".eval-feia" / "worktrees" / "run-1").resolve()
    candidate = CandidateManifestRecord(
        id="cand-001",
        worktree_path=worktree_root / "cand-001",
        result_dir=output / "candidates" / "cand-001",
        session_id="ses_1",
        status="passed",
    )
    return Manifest(
        run_id="run-1",
        created_at=utc_now_iso(),
        repo=RepoRecord(path=repo, base_ref="HEAD", base_sha="abc123"),
        server=ServerRecord(url="http://127.0.0.1:4096", version="test"),
        output_dir=output,
        worktree_root=worktree_root,
        candidates=[candidate],
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=eval-feia",
            "-c",
            "user.email=eval-feia@example.test",
            "commit",
            "-m",
            "init",
        ],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return path.resolve()
