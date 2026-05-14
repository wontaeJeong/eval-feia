from __future__ import annotations

from pathlib import Path

import pytest

from eval_feia.clean import clean_resources, plan_cleanup
from eval_feia.errors import CleanupSafetyError
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


def _manifest(tmp_path: Path) -> Manifest:
    repo = (tmp_path / "repo").resolve()
    repo.mkdir()
    output = (tmp_path / "repo" / ".eval-feia" / "runs" / "run-1").resolve()
    worktree_root = (tmp_path / "repo" / ".eval-feia" / "worktrees" / "run-1").resolve()
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
