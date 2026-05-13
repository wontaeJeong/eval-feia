from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from .models import WorktreeInfo


def resolve_base_commit(repo: Path, ref: str = "HEAD") -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", ref],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def create_worktree(
    repo: Path,
    run_root: Path,
    base_ref: str,
    base_commit: str,
    on_created: Callable[[Path], None] | None = None,
) -> WorktreeInfo:
    run_root.mkdir(parents=True, exist_ok=True)
    worktree_path = (run_root / "worktree").resolve()
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "--detach", str(worktree_path), base_commit],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if on_created is not None:
        on_created(worktree_path)
    return WorktreeInfo(path=str(worktree_path), base_ref=base_ref, base_commit=base_commit)


def remove_worktree(repo: Path, worktree_path: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree_path)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
