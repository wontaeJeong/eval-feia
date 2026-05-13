from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .reports import read_json
from .worktree import remove_worktree


class CleanupError(RuntimeError):
    pass


def cleanup_from_manifest(manifest_path: Path) -> list[Path]:
    manifest = read_json(manifest_path)
    repo = Path(str(manifest.get("repo", "."))).resolve()
    removed: list[Path] = []
    runs = manifest.get("runs", [])
    if not isinstance(runs, list):
        raise CleanupError("manifest runs must be a list")
    for run in runs:
        if not isinstance(run, dict):
            continue
        worktree = _path_from_run(run, "worktree", "path")
        if worktree:
            remove_worktree(repo, worktree)
            removed.append(worktree)
        temp_dir = _path_from_run(run, "temp_dir")
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir)
            removed.append(temp_dir)
    return removed


def _path_from_run(run: dict[str, Any], *keys: str) -> Path | None:
    value: Any = run
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    if isinstance(value, str) and value:
        return Path(value).resolve()
    return None
