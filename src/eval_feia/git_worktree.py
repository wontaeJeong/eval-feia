from __future__ import annotations

import re
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


@dataclass(slots=True)
class CreatedWorktree:
    path: Path
    branch_name: str


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

    def create_branch_worktree(
        self,
        worktree_root: Path,
        path_slug: str,
        base_ref: str,
        branch_name: str,
    ) -> CreatedWorktree:
        if not self.is_valid_branch_name(branch_name):
            raise GitError(
                "generated branch name is not a valid git branch",
                details={"branch_name": branch_name},
            )

        root = worktree_root.expanduser().resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)
        safe_slug = sanitize_path_slug(path_slug, fallback="worktree")
        last_collision: dict[str, str] = {}
        for suffix in range(1, 1000):
            candidate_branch = append_branch_suffix(branch_name, suffix)
            candidate_path = (root / append_path_suffix(safe_slug, suffix)).resolve(strict=False)
            if candidate_path.exists():
                last_collision = {"kind": "worktree_path", "path": str(candidate_path)}
                continue
            if self.branch_exists(candidate_branch):
                last_collision = {"kind": "branch", "branch_name": candidate_branch}
                continue
            _ = self._git("worktree", "add", "-b", candidate_branch, str(candidate_path), base_ref)
            return CreatedWorktree(path=candidate_path, branch_name=candidate_branch)
        raise GitError(
            "could not allocate a unique branch/worktree name",
            details={"branch_name": branch_name, **last_collision},
        )

    def branch_exists(self, branch_name: str) -> bool:
        result = _run_git_no_raise(
            [
                "git",
                "-C",
                str(self.repo_path),
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{branch_name}",
            ]
        )
        return result.returncode == 0

    def is_valid_branch_name(self, branch_name: str) -> bool:
        if not branch_name or branch_name == "@" or branch_name.startswith("-"):
            return False
        if branch_name.startswith("@{-"):
            return False
        result = _run_git_no_raise(
            ["git", "-C", str(self.repo_path), "check-ref-format", "--branch", branch_name]
        )
        return result.returncode == 0

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
    result = _run_git_no_raise(args)
    if result.returncode != 0:
        raise GitError(
            "git command failed",
            details={
                "args": list(args),
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
    return result


def _run_git_no_raise(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def sanitize_branch_name(value: str | None, fallback: str) -> str:
    for raw in (value, fallback, "eval/candidate"):
        cleaned = _sanitize_branch_text(raw or "")
        if cleaned:
            return cleaned
    return "eval/candidate"


def append_branch_suffix(branch_name: str, suffix: int) -> str:
    if suffix <= 1:
        return branch_name
    return f"{branch_name}-{suffix}"


def branch_name_to_path_slug(branch_name: str) -> str:
    return sanitize_path_slug(branch_name.replace("/", "-"), fallback="worktree")


def append_path_suffix(path_slug: str, suffix: int) -> str:
    if suffix <= 1:
        return path_slug
    return f"{path_slug}-{suffix}"


def sanitize_path_slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"\s+", "-", value.strip())
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = re.sub(r"_+", "_", slug)
    slug = slug.strip(" .-")
    return slug or fallback


def _sanitize_branch_text(value: str) -> str:
    name = re.sub(r"\s+", "-", value.strip())
    name = name.replace("@{", "-")
    name = name.replace("\\", "-")
    name = re.sub(r"[\x00-\x20\x7f~^:?*\[\]]+", "-", name)
    while ".." in name:
        name = name.replace("..", "-")
    name = re.sub(r"/+", "/", name)
    name = re.sub(r"-+", "-", name)
    name = re.sub(r"_+", "_", name)
    components: list[str] = []
    for component in name.split("/"):
        cleaned = component.strip(" .-")
        while cleaned.endswith(".lock"):
            cleaned = cleaned[: -len(".lock")].rstrip(" .-")
        if cleaned and cleaned != "@":
            components.append(cleaned)
    name = "/".join(components).strip("/ .-")
    if name == "@" or name.startswith("-") or name.startswith("@{-"):
        return ""
    return name
