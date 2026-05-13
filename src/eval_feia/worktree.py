from __future__ import annotations

import subprocess
from pathlib import Path

from .models import WorktreeInfo, utc_now_iso


class WorktreeError(RuntimeError):
    pass


def git(repo: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        text=True,
        capture_output=True,
    )


def resolve_base_commit(repo: Path, branch: str) -> str:
    result = git(repo, ["rev-parse", branch])
    return result.stdout.strip()


def create_worktree(repo: Path, path: Path, base_ref: str, base_commit: str | None = None) -> WorktreeInfo:
    repo = repo.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    commit = base_commit or resolve_base_commit(repo, base_ref)
    try:
        git(repo, ["worktree", "add", "--detach", str(path), commit])
    except subprocess.CalledProcessError as exc:
        raise WorktreeError(exc.stderr.strip() or exc.stdout.strip() or str(exc)) from exc
    return WorktreeInfo(path=str(path.resolve()), base_ref=base_ref, base_commit=commit, created_at=utc_now_iso())


def remove_worktree(repo: Path, path: Path) -> bool:
    result = git(repo, ["worktree", "remove", "--force", str(path)], check=False)
    if result.returncode == 0:
        return True
    if not path.exists():
        return True
    return False
