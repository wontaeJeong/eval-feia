from __future__ import annotations

import subprocess
from pathlib import Path

from eval_feia.git_worktree import (
    GitWorktreeManager,
    branch_name_to_path_slug,
    sanitize_branch_name,
)


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


def test_git_worktree_create_branch_worktree_with_collision_suffix(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = GitWorktreeManager(repo)
    root = tmp_path / "worktrees"

    first = manager.create_branch_worktree(root, "eval-foo", "HEAD", "eval/foo")
    second = manager.create_branch_worktree(root, "eval-foo", "HEAD", "eval/foo")

    assert first.branch_name == "eval/foo"
    assert second.branch_name == "eval/foo-2"
    assert first.path.name == "eval-foo"
    assert second.path.name == "eval-foo-2"
    assert _current_branch(first.path) == "eval/foo"
    assert _current_branch(second.path) == "eval/foo-2"

    manager.remove_worktree(first.path, force=True)
    manager.remove_worktree(second.path, force=True)


def test_branch_name_sanitization_outputs_git_valid_branch_names(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = GitWorktreeManager(repo)
    cases = {
        "hello world": "hello-world",
        "eval/foo bar": "eval/foo-bar",
        "../bad branch": "bad-branch",
        "feature:bad": "feature-bad",
        "": "eval/fallback",
    }

    for raw, expected in cases.items():
        branch = sanitize_branch_name(raw, "eval/fallback")
        assert branch == expected
        assert manager.is_valid_branch_name(branch)

    assert branch_name_to_path_slug("eval/foo-bar") == "eval-foo-bar"


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


def _current_branch(worktree: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(worktree), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
