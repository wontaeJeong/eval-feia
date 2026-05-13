from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from .models import WorktreeInfo


class WorktreeError(RuntimeError):
    pass


def resolve_base_commit(repo: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ref],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise WorktreeError(result.stderr.strip() or f"failed to resolve {ref}")
    return result.stdout.strip()


class WorktreeManager:
    def __init__(self, repo: Path, base_ref: str, base_commit: str):
        self.repo = repo.resolve()
        self.base_ref = base_ref
        self.base_commit = base_commit

    def create(self, run_id: str, run_temp_dir: Path, emit: Callable[[dict[str, Any]], None] | None = None) -> WorktreeInfo:
        run_temp_dir.mkdir(parents=True, exist_ok=True)
        worktree_path = (run_temp_dir / "worktree").resolve()
        if worktree_path.exists():
            raise WorktreeError(f"worktree already exists: {worktree_path}")
        result = subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "add", "--detach", str(worktree_path), self.base_commit],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise WorktreeError(result.stderr.strip() or "git worktree add failed")
        info = WorktreeInfo(path=worktree_path, base_ref=self.base_ref, base_commit=self.base_commit)
        if emit is not None:
            emit({"type": "worktree_created", "run_id": run_id, "path": str(info.path), "commit": info.base_commit})
        return info


def remove_worktree(repo: Path, worktree_path: Path) -> None:
    if worktree_path.exists():
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree_path)],
            check=False,
            capture_output=True,
            text=True,
        )
    if worktree_path.exists():
        shutil.rmtree(worktree_path)
