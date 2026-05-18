from __future__ import annotations

import os
from pathlib import Path


BASE_DIR_ENV = "EVAL_FEIA_BASE_DIR"
DEFAULT_BASE_ROOT = Path("~/.eval-feia")
OUTPUT_DIR_NAME = "output"
WORKTREES_DIR_NAME = "worktrees"
RESULTS_DIR_NAME = "results"
RUNS_DIR_NAME = "runs"


def configured_base_root(root: Path | None = None) -> Path:
    if root is None:
        configured = os.environ.get(BASE_DIR_ENV)
        root = Path(configured) if configured else DEFAULT_BASE_ROOT
    return root.expanduser()


def output_root_for_base(root: Path | None = None) -> Path:
    return configured_base_root(root)


def worktree_root_for_base(root: Path | None = None) -> Path:
    return configured_base_root(root)


def results_root_for_base(root: Path | None = None) -> Path:
    return configured_base_root(root)


def run_root_for_base(run_id: str, root: Path | None = None) -> Path:
    return configured_base_root(root) / run_id


def output_dir_for_run(run_id: str, root: Path | None = None) -> Path:
    return run_root_for_base(run_id, root) / OUTPUT_DIR_NAME


def worktree_dir_for_run(run_id: str, root: Path | None = None) -> Path:
    return run_root_for_base(run_id, root) / WORKTREES_DIR_NAME


def results_dir_for_run(run_id: str, root: Path | None = None) -> Path:
    return run_root_for_base(run_id, root) / RESULTS_DIR_NAME


def base_root_for_output_root(output_root: Path) -> Path:
    expanded = output_root.expanduser()
    if expanded.name == OUTPUT_DIR_NAME:
        return expanded.parent.parent
    if expanded.name == RUNS_DIR_NAME:
        return expanded.parent
    return expanded
