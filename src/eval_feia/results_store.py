from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .manifest import utc_now_iso
from .paths import RESULTS_DIR_NAME, configured_base_root, results_dir_for_run


RESULTS_DIR_ENV = "EVAL_FEIA_RESULTS_DIR"
DEFAULT_RESULT_FILE = "output.txt"
RESULTS_MARKER = ".eval-feia-results"
RESULTS_MARKER_TEXT = "eval-feia results\n"
RESULTS_OWNED_ENTRIES = frozenset(
    {
        RESULTS_MARKER,
        "index.jsonl",
        "runs",
        "metadata.json",
        "output.txt",
        "summary.txt",
        "stdout.log",
        "stderr.log",
        "run.log",
        "error.json",
        "manifest.json",
        "run-summary.json",
        "run-summary.md",
    }
)


def configured_results_root(root: Path | None = None) -> Path:
    if root is None:
        configured = os.environ.get(RESULTS_DIR_ENV)
        root = Path(configured) if configured else configured_base_root()
    return root.expanduser()


def resolve_results_root(root: Path | None = None) -> Path:
    return configured_results_root(root).resolve(strict=False)


def run_directory(run_id: str, root: Path | None = None) -> Path:
    _validate_run_id(run_id)
    root_path = resolve_results_root(root)
    if _uses_run_results_dir(run_id, root, root_path):
        run_path = root_path if root_path.name == RESULTS_DIR_NAME else results_dir_for_run(run_id, root_path)
        safety_root = run_path if root_path.name == RESULTS_DIR_NAME else root_path
    else:
        runs_root = root_path / "runs"
        run_path = runs_root / run_id
        safety_root = root_path
        if runs_root.is_symlink():
            raise ValueError(f"results runs path is not a directory: {runs_root}")
    if run_path.is_symlink():
        raise ValueError(f"stored run directory is a symlink: {run_path}")
    resolved = run_path.resolve(strict=False)
    if not _is_relative_to(resolved, safety_root):
        raise ValueError("stored run directory must stay inside the results root")
    return resolved


def start_run_record(
    run_id: str,
    *,
    cwd: Path,
    branch: str | None,
    label: str | None,
    command: str | None,
    root: Path | None = None,
) -> dict[str, Any]:
    output_dir = run_directory(run_id, root)
    metadata = {
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "finished_at": None,
        "status": "running",
        "cwd": str(cwd.expanduser().resolve(strict=False)),
        "output_dir": str(output_dir),
        "branch": branch,
        "label": label,
        "command": command,
        "exit_code": None,
    }
    _write_metadata(metadata, root=root)
    _append_index(metadata, root=root)
    return metadata


def complete_run_record(
    run_id: str,
    *,
    status: str,
    exit_code: int,
    output_text: str,
    summary_text: str,
    stdout_text: str,
    stderr_text: str,
    error: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    metadata = load_metadata(run_id, root=root)
    metadata.update(
        {
            "finished_at": utc_now_iso(),
            "status": status,
            "exit_code": exit_code,
        }
    )
    if extra:
        metadata.update(extra)

    output_dir = run_directory(run_id, root)
    _write_text(output_dir / "output.txt", output_text)
    _write_text(output_dir / "summary.txt", summary_text)
    _write_text(output_dir / "stdout.log", stdout_text)
    _write_text(output_dir / "stderr.log", stderr_text)
    _write_text(output_dir / "run.log", stdout_text + stderr_text)
    if error is not None:
        _atomic_write_json(output_dir / "error.json", error)
    _write_metadata(metadata, root=root)
    _append_index(metadata, root=root)
    return metadata


def load_metadata(run_id: str, root: Path | None = None) -> dict[str, Any]:
    metadata_path = run_directory(run_id, root) / "metadata.json"
    with metadata_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"metadata is not an object: {metadata_path}")
    return data


def list_run_metadata(root: Path | None = None) -> list[dict[str, Any]]:
    resolved_root = resolve_results_root(root)
    if _uses_base_results_layout(root) or _looks_like_base_root(resolved_root):
        records = _scan_base_metadata(resolved_root)
    elif resolved_root.name == RESULTS_DIR_NAME and (resolved_root / "metadata.json").exists():
        records = _scan_direct_results_metadata(resolved_root)
    else:
        records = _read_index_records(resolved_root)
    if records is None:
        records = _scan_metadata(resolved_root)

    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        run_id = record.get("run_id")
        if isinstance(run_id, str) and run_id:
            if not _metadata_path_for_listed_run(run_id, root, resolved_root).exists():
                continue
            latest[run_id] = record
    return sorted(
        latest.values(),
        key=lambda item: str(item.get("created_at") or item.get("run_id") or ""),
        reverse=True,
    )


def result_file_path(
    run_id: str,
    file_name: str | Path | None = None,
    *,
    root: Path | None = None,
) -> Path:
    base = run_directory(run_id, root).resolve(strict=False)
    relative = Path(file_name or DEFAULT_RESULT_FILE)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("result file must be a relative path inside the run directory")
    target = (base / relative).resolve(strict=False)
    if not _is_relative_to(target, base):
        raise ValueError("result file must stay inside the run directory")
    if not target.exists():
        raise FileNotFoundError(target)
    if not target.is_file():
        raise IsADirectoryError(target)
    return target


def read_result_file(
    run_id: str,
    file_name: str | Path | None = None,
    *,
    root: Path | None = None,
) -> str:
    return result_file_path(run_id, file_name, root=root).read_text(encoding="utf-8")


def _validate_run_id(run_id: str) -> None:
    if not run_id or not run_id.strip():
        raise ValueError("run_id must not be empty")
    if run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
        raise ValueError("run_id must be a single path segment")


def _uses_base_results_layout(root: Path | None) -> bool:
    return root is None and not os.environ.get(RESULTS_DIR_ENV)


def _looks_like_base_root(root: Path) -> bool:
    if root.name == RESULTS_DIR_NAME or (root / RESULTS_MARKER).exists():
        return False
    return root.exists()


def _uses_run_results_dir(run_id: str, root: Path | None, resolved_root: Path) -> bool:
    if root is None:
        return not os.environ.get(RESULTS_DIR_ENV)
    return resolved_root.name == RESULTS_DIR_NAME and resolved_root.parent.name == run_id


def _write_metadata(metadata: dict[str, Any], *, root: Path | None = None) -> None:
    run_id = str(metadata["run_id"])
    _ensure_results_root(run_id, root)
    output_dir = run_directory(run_id, root)
    metadata = dict(metadata)
    metadata["output_dir"] = str(output_dir)
    _atomic_write_json(output_dir / "metadata.json", metadata)


def _append_index(metadata: dict[str, Any], *, root: Path | None = None) -> None:
    run_id = str(metadata["run_id"])
    index_path = _index_path_for_run(run_id, root)
    with index_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())


def _ensure_results_root(run_id: str, root: Path | None = None) -> Path:
    resolved_root = resolve_results_root(root)
    if _uses_run_results_dir(run_id, root, resolved_root):
        results_root = run_directory(run_id, root)
    else:
        results_root = resolved_root
    if results_root.exists():
        _validate_results_root_for_write(results_root)
    else:
        results_root.mkdir(parents=True)
    marker = results_root / RESULTS_MARKER
    if not marker.exists():
        marker.write_text(RESULTS_MARKER_TEXT, encoding="utf-8")
    return results_root


def _index_path_for_run(run_id: str, root: Path | None = None) -> Path:
    resolved_root = resolve_results_root(root)
    if _uses_run_results_dir(run_id, root, resolved_root):
        return _ensure_results_root(run_id, root) / "index.jsonl"
    return _ensure_results_root(run_id, root) / "index.jsonl"


def _validate_results_root_for_write(root: Path) -> None:
    if not root.is_dir():
        raise ValueError(f"results root is not a directory: {root}")
    marker = root / RESULTS_MARKER
    entries = list(root.iterdir())
    if not marker.exists():
        if entries:
            raise ValueError(f"refusing to initialize non-empty results root: {root}")
        return
    if marker.is_symlink() or not marker.is_file() or marker.read_text(encoding="utf-8") != RESULTS_MARKER_TEXT:
        raise ValueError(f"results root marker is invalid: {marker}")
    unexpected = sorted(path.name for path in entries if path.name not in RESULTS_OWNED_ENTRIES)
    if unexpected:
        raise ValueError("results root contains unexpected entries: " + ", ".join(unexpected))
    index_path = root / "index.jsonl"
    if index_path.exists() and (index_path.is_symlink() or not index_path.is_file()):
        raise ValueError(f"results index is not a regular file: {index_path}")
    runs_root = root / "runs"
    if runs_root.exists() and (runs_root.is_symlink() or not runs_root.is_dir()):
        raise ValueError(f"results runs path is not a directory: {runs_root}")


def _read_index_records(root: Path) -> list[dict[str, Any]] | None:
    index_path = root / "index.jsonl"
    if not index_path.exists():
        return None
    records: list[dict[str, Any]] = []
    try:
        with index_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                record = json.loads(stripped)
                if not isinstance(record, dict):
                    return None
                records.append(record)
    except (OSError, json.JSONDecodeError):
        return None
    return records


def _scan_metadata(root: Path) -> list[dict[str, Any]]:
    runs_root = root / "runs"
    if not runs_root.exists():
        return []
    records: list[dict[str, Any]] = []
    for metadata_path in sorted(runs_root.glob("*/metadata.json")):
        try:
            with metadata_path.open("r", encoding="utf-8") as fh:
                record = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _scan_base_metadata(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    records: list[dict[str, Any]] = []
    for metadata_path in sorted(root.glob(f"*/{RESULTS_DIR_NAME}/metadata.json")):
        try:
            with metadata_path.open("r", encoding="utf-8") as fh:
                record = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _scan_direct_results_metadata(root: Path) -> list[dict[str, Any]]:
    metadata_path = root / "metadata.json"
    try:
        with metadata_path.open("r", encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    return [record] if isinstance(record, dict) else []


def _metadata_path_for_listed_run(run_id: str, root: Path | None, resolved_root: Path) -> Path:
    if _uses_base_results_layout(root):
        return results_dir_for_run(run_id, resolved_root) / "metadata.json"
    if resolved_root.name == RESULTS_DIR_NAME and resolved_root.parent.name == run_id:
        return resolved_root / "metadata.json"
    if _looks_like_base_root(resolved_root):
        return results_dir_for_run(run_id, resolved_root) / "metadata.json"
    return run_directory(run_id, resolved_root) / "metadata.json"


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(value, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
