from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from .manifest import Manifest, load_manifest
from .paths import OUTPUT_DIR_NAME, RUNS_DIR_NAME, output_root_for_base
from .plain_table import print_plain_table


@dataclass(slots=True)
class SavedRun:
    run_id: str
    created_at: str
    modified_at: str
    label: str | None
    branches: list[str]
    output_path: Path
    result_path: Path
    metadata_path: Path | None
    warning: str | None
    _modified_timestamp: float

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "label": self.label,
            "branches": self.branches,
            "output_path": str(self.output_path),
            "result_path": str(self.result_path),
            "metadata_path": str(self.metadata_path) if self.metadata_path is not None else None,
            "warning": self.warning,
        }


def default_runs_root(base_dir: Path | None = None) -> Path:
    root = output_root_for_base().expanduser()
    if not root.is_absolute():
        root = (base_dir or Path.cwd()) / root
    return root.resolve(strict=False)


def list_saved_runs(*, output_root: Path | None = None, limit: int | None = None) -> list[SavedRun]:
    root = (output_root or default_runs_root()).expanduser().resolve(strict=False)
    if not root.is_dir():
        return []

    runs = [_read_run(run_dir) for run_dir in _iter_run_output_dirs(root)]
    runs.sort(key=lambda run: run._modified_timestamp, reverse=True)
    if limit is not None:
        return runs[:limit]
    return runs


def _iter_run_output_dirs(root: Path) -> list[Path]:
    run_dirs: list[Path] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name == RUNS_DIR_NAME:
            run_dirs.extend(child for child in entry.iterdir() if child.is_dir())
            continue
        output_dir = entry / OUTPUT_DIR_NAME
        if output_dir.is_dir():
            run_dirs.append(output_dir)
        else:
            run_dirs.append(entry)
    return run_dirs


def print_saved_runs(console: Console, runs: list[SavedRun]) -> None:
    if not runs:
        console.print("No saved runs found.", markup=False)
        return

    for run in runs:
        if run.warning is not None:
            console.print(f"warning: {run.run_id}: {run.warning}", style="yellow", markup=False)

    print_plain_table(
        console,
        ("RUN", "CREATED", "MODIFIED", "LABEL", "BRANCH", "OUTPUT", "RESULT"),
        [
            (
                run.run_id,
                run.created_at,
                run.modified_at,
                run.label or "",
                _format_branches(run.branches),
                str(run.output_path),
                str(run.result_path),
            )
            for run in runs
        ],
    )


def saved_runs_json(runs: list[SavedRun]) -> str:
    return json.dumps([run.to_json() for run in runs], indent=2, ensure_ascii=False)


def _read_run(run_dir: Path) -> SavedRun:
    manifest_path = run_dir / "manifest.json"
    summary_path = run_dir / "run-summary.json"
    candidate_result_paths = sorted((run_dir / "candidates").glob("*/result.json"))

    manifest, manifest_warning = _load_manifest(manifest_path)
    summary, summary_warning = _load_json(summary_path)
    candidate_results, candidate_warnings = _load_candidate_results(candidate_result_paths)

    modified_timestamp = _latest_mtime([run_dir, manifest_path, summary_path, *candidate_result_paths])
    modified_at = _format_timestamp(modified_timestamp)
    run_id = _run_id(run_dir, manifest, summary)
    created_at = _created_at(run_dir, manifest, modified_timestamp)
    label = _label(manifest, summary)
    branches = _branches(manifest, summary, candidate_results)
    output_path = _output_path(run_dir, manifest, summary)
    result_path = _result_path(run_dir, summary_path, manifest_path, candidate_result_paths)
    metadata_path = _metadata_path(manifest_path, summary_path)
    warning = _join_warnings([manifest_warning, summary_warning, *candidate_warnings])

    return SavedRun(
        run_id=run_id,
        created_at=created_at,
        modified_at=modified_at,
        label=label,
        branches=branches,
        output_path=output_path,
        result_path=result_path,
        metadata_path=metadata_path,
        warning=warning,
        _modified_timestamp=modified_timestamp,
    )


def _load_manifest(path: Path) -> tuple[Manifest | None, str | None]:
    if not path.exists():
        return None, None
    try:
        return load_manifest(path), None
    except Exception as exc:
        return None, f"failed to parse manifest.json: {exc}"


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"failed to parse {path.name}: {exc}"
    if not isinstance(value, dict):
        return None, f"failed to parse {path.name}: expected object"
    return value, None


def _load_candidate_results(paths: list[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    for path in paths:
        value, warning = _load_json(path)
        if value is not None:
            results.append(value)
        if warning is not None:
            warnings.append(warning)
    return results, warnings


def _run_id(run_dir: Path, manifest: Manifest | None, summary: dict[str, Any] | None) -> str:
    if manifest is not None:
        return manifest.run_id
    if summary is not None:
        value = summary.get("run_id")
        if isinstance(value, str) and value:
            return value
    return run_dir.name


def _created_at(run_dir: Path, manifest: Manifest | None, fallback_timestamp: float) -> str:
    if manifest is not None:
        return manifest.created_at
    try:
        return _format_timestamp(run_dir.stat().st_mtime)
    except OSError:
        return _format_timestamp(fallback_timestamp)


def _label(manifest: Manifest | None, summary: dict[str, Any] | None) -> str | None:
    if manifest is not None and manifest.label:
        return manifest.label
    if summary is not None:
        value = summary.get("label")
        if isinstance(value, str) and value:
            return value
    return None


def _branches(
    manifest: Manifest | None,
    summary: dict[str, Any] | None,
    candidate_results: list[dict[str, Any]],
) -> list[str]:
    branches: list[str] = []
    if manifest is not None:
        branches.extend(
            record.branch_name for record in manifest.candidates if record.branch_name is not None
        )
    if not branches and summary is not None:
        branches.extend(_candidate_branches(summary.get("candidates")))
    if not branches:
        for result in candidate_results:
            value = result.get("branch_name")
            if isinstance(value, str) and value:
                branches.append(value)
    return _unique(branches)


def _candidate_branches(candidates: object) -> list[str]:
    if not isinstance(candidates, list):
        return []
    branches: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        value = candidate.get("branch_name")
        if isinstance(value, str) and value:
            branches.append(value)
    return branches


def _output_path(
    run_dir: Path,
    manifest: Manifest | None,
    summary: dict[str, Any] | None,
) -> Path:
    if manifest is not None:
        return manifest.output_dir
    if summary is not None:
        value = summary.get("output_dir")
        if isinstance(value, str) and value:
            return Path(value)
    return run_dir


def _result_path(
    run_dir: Path,
    summary_path: Path,
    manifest_path: Path,
    candidate_result_paths: list[Path],
) -> Path:
    for path in [summary_path, manifest_path, *candidate_result_paths]:
        if path.exists():
            return path
    return run_dir


def _metadata_path(manifest_path: Path, summary_path: Path) -> Path | None:
    if manifest_path.exists():
        return manifest_path
    if summary_path.exists():
        return summary_path
    return None


def _latest_mtime(paths: list[Path]) -> float:
    timestamps: list[float] = []
    for path in paths:
        try:
            timestamps.append(path.stat().st_mtime)
        except OSError:
            continue
    if timestamps:
        return max(timestamps)
    return datetime.now().timestamp()


def _format_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")


def _format_branches(branches: list[str]) -> str:
    if len(branches) <= 2:
        return ", ".join(branches)
    return ", ".join(branches[:2]) + f" (+{len(branches) - 2})"


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values


def _join_warnings(warnings: list[str | None]) -> str | None:
    present = [warning for warning in warnings if warning]
    if not present:
        return None
    return "; ".join(present)
