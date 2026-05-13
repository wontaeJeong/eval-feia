from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .reports import load_manifest
from .worktree import WORKTREE_MARKER


class CleanupError(RuntimeError):
    pass


def manifest_owned_paths(manifest: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    root_value = manifest.get("worktree_root")
    root = Path(root_value).resolve() if isinstance(root_value, str) and root_value else None
    for run in manifest.get("runs", []):
        if not isinstance(run, dict):
            continue
        worktree = run.get("worktree") or {}
        path = worktree.get("path") if isinstance(worktree, dict) else run.get("worktree_path")
        if path:
            resolved = Path(path).resolve()
            _assert_safe_worktree_path(resolved, root)
            paths.append(resolved)
    return paths


def _assert_safe_worktree_path(path: Path, root: Path | None) -> None:
    if not path.is_absolute():
        raise CleanupError(f"refusing non-absolute path: {path}")
    if path.name != "worktree":
        raise CleanupError(f"refusing non-worktree path: {path}")
    if root is None:
        raise CleanupError("manifest missing worktree_root")
    if not path.is_relative_to(root):
        raise CleanupError(f"refusing path outside worktree_root: {path}")
    if path in {Path("/").resolve(), Path.home().resolve(), root}:
        raise CleanupError(f"refusing unsafe path: {path}")
    if path.is_symlink():
        raise CleanupError(f"refusing symlink path: {path}")
    if path.exists() and not (path / WORKTREE_MARKER).is_file():
        raise CleanupError(f"missing eval-feia worktree marker: {path}")


def cleanup_manifest(manifest_path: Path) -> list[Path]:
    manifest_path = manifest_path.resolve()
    if not manifest_path.exists():
        raise CleanupError(f"manifest not found: {manifest_path}")
    manifest = load_manifest(manifest_path)
    repo_value = manifest.get("repo")
    repo = Path(repo_value).resolve() if isinstance(repo_value, str) and repo_value else None
    owned = manifest_owned_paths(manifest)
    removed: list[Path] = []
    for path in owned:
        run_root = path.parent
        had_marker = (path / WORKTREE_MARKER).is_file()
        if path.exists():
            _git_worktree_remove(repo, path)
            if path.exists():
                shutil.rmtree(path)
        if had_marker and run_root.exists() and _safe_run_root(run_root, path):
            shutil.rmtree(run_root)
            removed.append(run_root)
        elif not path.exists():
            removed.append(path)
    return removed


def _git_worktree_remove(repo: Path | None, path: Path) -> None:
    if repo is None or not repo.exists():
        return
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(path)],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def _safe_run_root(run_root: Path, worktree: Path) -> bool:
    return worktree.parent == run_root and run_root.name.startswith("run-") and run_root.parent.name.startswith("batch-")
