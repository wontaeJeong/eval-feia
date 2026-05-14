from __future__ import annotations

import subprocess
from pathlib import Path

from eval_feia.git_worktree import GitWorktreeManager


def test_git_worktree_create_collect_and_remove(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = GitWorktreeManager(repo)
    assert manager.ensure_repo() == repo.resolve()
    sha = manager.resolve_sha("HEAD")
    assert len(sha) >= 7

    worktree = manager.create_worktree(tmp_path / "worktrees" / "cand-001", "HEAD")
    assert (worktree / "README.md").exists()
    (worktree / "README.md").write_text("changed\n", encoding="utf-8")

    artifacts = manager.collect_local_artifacts(worktree)
    assert "README.md" in artifacts.diff_binary
    assert "README.md" in artifacts.diff_numstat

    manager.remove_worktree(worktree, force=True)
    assert not worktree.exists()


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
