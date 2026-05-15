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


def plan_cleanup(manifest: Manifest, manifest_path: Path | None = None) -> list[CleanupAction]:
    _validate_manifest_roots(manifest, manifest_path)
    actions: list[CleanupAction] = []
    worktree_root = _safe_resolved_path(manifest.worktree_root, manifest.repo.path)
    output_dir = _safe_resolved_path(manifest.output_dir, manifest.repo.path)
    candidate_root = output_dir / "candidates"
    for candidate in manifest.candidates:
        worktree = _safe_resolved_path(candidate.worktree_path, manifest.repo.path)
        result_dir = _safe_resolved_path(candidate.result_dir, manifest.repo.path)
        _validate_child_path(worktree, worktree_root)
        _validate_child_path(result_dir, candidate_root)
        actions.append(CleanupAction("worktree", worktree))
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
    actions = plan_cleanup(manifest, manifest_path)
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
            manager.remove_worktree(path, force=True)
            return
        except Exception:
            if not force:
                raise
    shutil.rmtree(path)


def _validate_manifest_roots(manifest: Manifest, manifest_path: Path | None) -> None:
    repo_root = manifest.repo.path.resolve(strict=False)
    output_dir = _safe_resolved_path(manifest.output_dir, manifest.repo.path)
    worktree_root = _safe_resolved_path(manifest.worktree_root, manifest.repo.path)
    for root in (output_dir, worktree_root):
        _validate_basic_path(root, repo_root)
    if output_dir.name != manifest.run_id:
        raise CleanupSafetyError("manifest output_dir must be the run_id directory")
    if worktree_root.name != manifest.run_id:
        raise CleanupSafetyError("manifest worktree_root must be the run_id directory")
    if output_dir == worktree_root or _is_relative_to(output_dir, worktree_root) or _is_relative_to(
        worktree_root, output_dir
    ):
        raise CleanupSafetyError("manifest output and worktree roots must not overlap")
    if manifest_path is not None:
        _validate_no_symlink_components(manifest_path)
        expected_manifest = (output_dir / "manifest.json").resolve(strict=False)
        actual_manifest = manifest_path.expanduser().resolve(strict=False)
        if actual_manifest != expected_manifest:
            raise CleanupSafetyError("manifest file must be located at output_dir/manifest.json")


def _safe_resolved_path(path: Path, repo_path: Path) -> Path:
    repo_root = repo_path.resolve(strict=False)
    _validate_no_symlink_components(path)
    resolved = path.expanduser().resolve(strict=False)
    _validate_basic_path(resolved, repo_root)
    return resolved


def _validate_child_path(path: Path, root: Path) -> None:
    if path == root or not _is_relative_to(path, root):
        raise CleanupSafetyError(f"refusing to delete path outside generated roots: {path}")


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


def _validate_no_symlink_components(path: Path) -> None:
    expanded = path.expanduser()
    current = Path(expanded.anchor) if expanded.is_absolute() else Path()
    parts = expanded.parts[1:] if expanded.is_absolute() else expanded.parts
    for part in parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise CleanupSafetyError(f"refusing to delete symlink path: {current}")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
