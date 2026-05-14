from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import GitError


@dataclass(slots=True)
class LocalGitArtifacts:
    status_short: str
    diff_stat: str
    diff_binary: str
    diff_numstat: str


class GitWorktreeManager:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path.expanduser().resolve(strict=False)

    def ensure_repo(self) -> Path:
        result = self._git("rev-parse", "--show-toplevel")
        root = Path(result.stdout.strip()).resolve(strict=False)
        if not root.exists():
            raise GitError(f"git repository root does not exist: {root}")
        self.repo_path = root
        return root

    def resolve_sha(self, ref: str) -> str:
        return self._git("rev-parse", "--verify", ref).stdout.strip()

    def create_worktree(self, worktree_path: Path, base_ref: str) -> Path:
        path = worktree_path.expanduser().resolve(strict=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = self._git("worktree", "add", "--detach", str(path), base_ref)
        return path

    def remove_worktree(self, worktree_path: Path, *, force: bool = False) -> None:
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(worktree_path))
        _ = self._git(*args)

    def collect_local_artifacts(self, worktree_path: Path) -> LocalGitArtifacts:
        return LocalGitArtifacts(
            status_short=self._git_in_worktree(worktree_path, "status", "--short").stdout,
            diff_stat=self._git_in_worktree(worktree_path, "diff", "--stat").stdout,
            diff_binary=self._git_in_worktree(worktree_path, "diff", "--binary").stdout,
            diff_numstat=self._git_in_worktree(worktree_path, "diff", "--numstat").stdout,
        )

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return _run_git(["git", "-C", str(self.repo_path), *args])

    @staticmethod
    def _git_in_worktree(worktree_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return _run_git(["git", "-C", str(worktree_path), *args])


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise GitError(
            "git command failed",
            details={
                "args": _safe_args(args),
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
    return result


def _safe_args(args: list[str]) -> list[str]:
    return [arg for arg in args]
