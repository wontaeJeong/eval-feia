from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .reports import read_json
from .worktree import remove_worktree


def cleanup_manifest(manifest_path: Path, dry_run: bool = False) -> list[dict[str, Any]]:
    manifest = read_json(manifest_path)
    repo = Path(manifest["repo"]).resolve()
    actions: list[dict[str, Any]] = []
    for run in manifest.get("runs", []):
        run_id = run.get("run_id")
        worktree = run.get("worktree", {}).get("path") if isinstance(run.get("worktree"), dict) else None
        if worktree:
            path = Path(worktree).resolve()
            actions.append({"run_id": run_id, "path": str(path), "kind": "worktree", "dry_run": dry_run})
            if not dry_run and path.exists():
                remove_worktree(repo, path)
        for raw in run.get("temp_paths", []):
            path = Path(raw).resolve()
            actions.append({"run_id": run_id, "path": str(path), "kind": "temp", "dry_run": dry_run})
            if not dry_run and path.exists():
                shutil.rmtree(path, ignore_errors=True)
    return actions
