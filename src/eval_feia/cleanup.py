from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .worktree import remove_worktree


MARKER_FILE = ".eval-feia-run"
ROOT_MARKER_FILE = ".eval-feia-root"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_delete_root(manifest: dict[str, Any], manifest_path: Path) -> Path:
    root_text = manifest.get("worktree_root")
    if root_text:
        root = Path(str(root_text)).resolve()
    else:
        root = manifest_path.parent.resolve()
    repo = Path(str(manifest.get("repo", "."))).resolve()
    dangerous = {Path("/").resolve(), Path.home().resolve(), Path.cwd().resolve(), repo}
    if root in dangerous or not (root / ROOT_MARKER_FILE).exists():
        raise ValueError(f"refusing unsafe cleanup root: {root}")
    return root


def _manifest_runs(manifest: dict[str, Any], manifest_path: Path) -> list[dict[str, Any]]:
    runs = [run for run in manifest.get("runs", []) if isinstance(run, dict)]
    seen = {str(run.get("run_id", "")) for run in runs}
    for run_json in sorted((manifest_path.parent / "runs").glob("*/run.json")):
        try:
            data = json.loads(run_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        run_id = str(data.get("run_id", run_json.parent.name))
        if run_id in seen:
            continue
        runs.append(data)
        seen.add(run_id)
    return runs


def _safe_temp_dir(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    dangerous = {Path("/").resolve(), Path.home().resolve(), Path.cwd().resolve()}
    return resolved not in dangerous and _is_relative_to(resolved, root) and (resolved / MARKER_FILE).exists()


def _safe_worktree_path(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    return _is_relative_to(resolved, root) and (resolved.parent / MARKER_FILE).exists()


def cleanup_from_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repo = Path(manifest["repo"])
    safe_root = _safe_delete_root(manifest, manifest_path)
    removed: list[str] = []
    failed: list[str] = []
    refused: list[str] = []
    for run in _manifest_runs(manifest, manifest_path):
        worktree_data = run.get("worktree", {}) if isinstance(run, dict) else {}
        path_text = worktree_data.get("path") or run.get("worktree_path")
        temp_run_dir_text = run.get("temp_run_dir")
        if path_text:
            path = Path(path_text)
            if not _safe_worktree_path(path, safe_root):
                refused.append(str(path))
                ok = False
            else:
                ok = remove_worktree(repo, path)
            if ok:
                removed.append(str(path))
            elif str(path) not in refused:
                failed.append(str(path))
        if temp_run_dir_text:
            temp_run_dir = Path(temp_run_dir_text)
            if temp_run_dir.exists():
                if _safe_temp_dir(temp_run_dir, safe_root):
                    shutil.rmtree(temp_run_dir)
                    removed.append(str(temp_run_dir))
                else:
                    refused.append(str(temp_run_dir))
    return {"removed": removed, "failed": failed, "refused": refused, "ok": not failed and not refused}
