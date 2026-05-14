from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .errors import CleanupSafetyError
from .git_worktree import GitWorktreeManager
from .manifest import Manifest, load_manifest


@dataclass(slots=True)
class CleanupAction:
    kind: str
    path: Path


@dataclass(slots=True)
class CleanupResult:
    actions: list[CleanupAction]
    errors: list[str]
    dry_run: bool


def plan_cleanup(manifest: Manifest) -> list[CleanupAction]:
    _validate_manifest_roots(manifest)
    actions: list[CleanupAction] = []
    for candidate in manifest.candidates:
        worktree = candidate.worktree_path.resolve(strict=False)
        _validate_safe_path(
            worktree,
            manifest,
            allow_exact_worktree=True,
            expected_root=manifest.worktree_root,
        )
        actions.append(CleanupAction("worktree", worktree))
    worktree_root = manifest.worktree_root.resolve(strict=False)
    output_dir = manifest.output_dir.resolve(strict=False)
    _validate_safe_path(worktree_root, manifest, expected_root=worktree_root)
    _validate_safe_path(output_dir, manifest, expected_root=output_dir)
    actions.append(CleanupAction("directory", worktree_root))
    actions.append(CleanupAction("directory", output_dir))
    return actions


def clean_resources(
    manifest_path: Path,
    *,
    dry_run: bool = False,
    force: bool = False,
    use_git: bool = True,
) -> CleanupResult:
    manifest = load_manifest(manifest_path)
    actions = plan_cleanup(manifest)
    errors: list[str] = []
    if dry_run:
        return CleanupResult(actions, errors, dry_run=True)

    manager = GitWorktreeManager(manifest.repo.path)
    for action in actions:
        try:
            if action.kind == "worktree":
                _remove_worktree(manager, action.path, force=force, use_git=use_git)
            elif action.path.exists():
                shutil.rmtree(action.path)
        except Exception as exc:
            errors.append(f"failed to remove {action.path}: {exc}")
            if not force:
                break
    return CleanupResult(actions, errors, dry_run=False)


def _remove_worktree(
    manager: GitWorktreeManager,
    path: Path,
    *,
    force: bool,
    use_git: bool,
) -> None:
    if not path.exists():
        return
    if use_git:
        try:
            manager.remove_worktree(path, force=force)
            return
        except Exception:
            if not force:
                raise
    shutil.rmtree(path)


def _validate_manifest_roots(manifest: Manifest) -> None:
    repo_root = manifest.repo.path.resolve(strict=False)
    for root in (manifest.output_dir.resolve(strict=False), manifest.worktree_root.resolve(strict=False)):
        _validate_basic_path(root, repo_root)


def _validate_safe_path(
    path: Path,
    manifest: Manifest,
    *,
    expected_root: Path,
    allow_exact_worktree: bool = False,
) -> None:
    repo_root = manifest.repo.path.resolve(strict=False)
    resolved = path.resolve(strict=False)
    _validate_basic_path(resolved, repo_root)
    if resolved.exists() and resolved.is_symlink():
        raise CleanupSafetyError(f"refusing to delete symlink path: {resolved}")
    root = expected_root.resolve(strict=False)
    if _is_relative_to(resolved, root):
        return
    if allow_exact_worktree and any(
        resolved == candidate.worktree_path.resolve(strict=False) for candidate in manifest.candidates
    ):
        return
    raise CleanupSafetyError(f"refusing to delete path outside generated roots: {resolved}")


def _validate_basic_path(path: Path, repo_root: Path) -> None:
    if str(path) in {"", "."}:
        raise CleanupSafetyError("refusing to delete empty path")
    home = Path.home().resolve(strict=False)
    if path == Path(path.anchor):
        raise CleanupSafetyError(f"refusing to delete filesystem root: {path}")
    if path == home:
        raise CleanupSafetyError(f"refusing to delete home directory: {path}")
    if path == repo_root:
        raise CleanupSafetyError(f"refusing to delete repository root: {path}")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
