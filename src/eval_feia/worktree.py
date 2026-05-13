from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, TextIO

from .models import WorktreeInfo
from .reports import JSONLRenderer

WORKTREE_MARKER = ".eval-feia-worktree"


class WorktreeError(RuntimeError):
    pass


class WorktreeManager:
    def __init__(self, repo: Path, temp_root: Path | None = None) -> None:
        self.repo = repo.resolve()
        self.temp_root = temp_root.resolve() if temp_root else Path(tempfile.mkdtemp(prefix="eval-feia-"))

    def resolve_base_commit(self, ref: str = "HEAD") -> str:
        result = subprocess.run(
            ["git", "rev-parse", ref],
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            raise WorktreeError(result.stderr.strip() or f"failed to resolve {ref}")
        return result.stdout.strip()

    def create_run_worktree(
        self,
        batch_id: str,
        run_id: str,
        base_ref: str = "HEAD",
        stream: TextIO | None = None,
        json_mode: bool = False,
        emit_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> WorktreeInfo:
        base_commit = self.resolve_base_commit(base_ref)
        run_root = (self.temp_root / batch_id / run_id).resolve()
        worktree_path = (run_root / "worktree").resolve()
        run_root.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree_path), base_commit],
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            raise WorktreeError(result.stderr.strip() or "failed to create worktree")
        (worktree_path / WORKTREE_MARKER).write_text("eval-feia owned worktree\n")
        info = WorktreeInfo(path=str(worktree_path), base_ref=base_ref, base_commit=base_commit)
        event = {"type": "worktree_created", "run_id": run_id, "path": info.path, "commit": base_commit}
        if emit_event:
            emit_event(event)
        elif stream is not None:
            if json_mode:
                JSONLRenderer(stream).emit(event)
            else:
                print(f"[{run_id}] worktree: {info.path}", file=stream, flush=True)
        return info
