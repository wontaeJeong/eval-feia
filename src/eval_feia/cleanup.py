from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .reports import read_json
from .worktree import remove_worktree


def _listed_worktrees(repo: Path) -> set[Path]:
    result = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    paths: set[Path] = set()
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            paths.add(Path(line.removeprefix("worktree ")).resolve())
    return paths


def _safe_manifest_path(raw: str, allowed: set[Path]) -> Path:
    path = Path(raw).expanduser()
    resolved = path.resolve()
    if path.is_symlink() or resolved not in allowed or resolved == Path(resolved.anchor):
        raise ValueError(f"refusing to remove non-owned path: {raw}")
    return resolved


def cleanup_manifest(manifest_path: Path, dry_run: bool = False) -> list[dict[str, Any]]:
    manifest = read_json(manifest_path)
    repo = Path(manifest["repo"]).resolve()
    actions: list[dict[str, Any]] = []
    registered_worktrees = _listed_worktrees(repo)
    for run in manifest.get("runs", []):
        run_id = run.get("run_id")
        worktree = run.get("worktree", {}).get("path") if isinstance(run.get("worktree"), dict) else None
        allowed_temp_paths: set[Path] = set()
        if worktree:
            path = _safe_manifest_path(worktree, {Path(worktree).resolve()})
            if path not in registered_worktrees:
                raise ValueError(f"refusing to remove unregistered worktree: {path}")
            run_root = path.parent
            allowed_temp_paths = {(run_root / "home").resolve(), (run_root / "tmp").resolve(), (run_root / "logs").resolve()}
            actions.append({"run_id": run_id, "path": str(path), "kind": "worktree", "dry_run": dry_run})
            if not dry_run and path.exists():
                remove_worktree(repo, path)
        for raw in run.get("temp_paths", []):
            path = _safe_manifest_path(raw, allowed_temp_paths)
            actions.append({"run_id": run_id, "path": str(path), "kind": "temp", "dry_run": dry_run})
            if not dry_run and path.exists():
                shutil.rmtree(path, ignore_errors=True)
    return actions
