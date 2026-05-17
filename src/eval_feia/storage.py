from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping

from .manifest import utc_now_iso
from .records import RunRow


DB_ENV_VAR = "EVAL_FEIA_DB_PATH"
DB_FILENAME = "eval-feia.sqlite3"
SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000
VALID_STATUSES = {"pending", "running", "success", "failed", "cancelled"}


class StorageError(RuntimeError):
    pass


def default_db_path(output_root: Path | None = None) -> Path:
    override = os.environ.get(DB_ENV_VAR)
    if override:
        return _absolute_path(Path(override))
    root = output_root or Path(".eval-feia/runs")
    return db_path_for_output_root(root)


def db_path_for_output_root(output_root: Path) -> Path:
    return _absolute_path(output_root) / DB_FILENAME


def init_db(db_path: Path) -> Path:
    resolved = _absolute_path(db_path)
    _ensure_db_parent(resolved)
    with _open_connection(resolved) as conn:
        try:
            journal_mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()
            if journal_mode is None or str(journal_mode[0]).lower() != "wal":
                raise StorageError("could not enable SQLite WAL journal mode")
            _migrate(conn)
            conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(format_storage_error(exc, resolved)) from exc
    return resolved


def create_run(
    db_path: Path,
    *,
    run_id: str,
    status: str = "pending",
    created_at: str | None = None,
    started_at: str | None = None,
    cwd: str | Path | None = None,
    repo_root: str | Path | None = None,
    branch: str | None = None,
    label: str | None = None,
    command: str | None = None,
    prompt: str | None = None,
    output_dir: str | Path | None = None,
    stdout_path: str | Path | None = None,
    stderr_path: str | Path | None = None,
    result_path: str | Path | None = None,
    summary_path: str | Path | None = None,
    exit_code: int | None = None,
    duration_ms: int | None = None,
    error_message: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    _validate_status(status)
    now = created_at or utc_now_iso()
    fields: dict[str, Any] = {
        "id": run_id,
        "created_at": now,
        "updated_at": now,
        "started_at": started_at,
        "ended_at": None,
        "status": status,
        "cwd": _path_or_none(cwd),
        "repo_root": _path_or_none(repo_root),
        "branch": branch,
        "label": label,
        "command": command,
        "prompt": prompt,
        "output_dir": _path_or_none(output_dir),
        "stdout_path": _path_or_none(stdout_path),
        "stderr_path": _path_or_none(stderr_path),
        "result_path": _path_or_none(result_path),
        "summary_path": _path_or_none(summary_path),
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "error_message": error_message,
        "metadata_json": _metadata_json(metadata),
    }
    columns = tuple(fields.keys())
    placeholders = ", ".join("?" for _ in columns)
    sql = f"INSERT INTO runs ({', '.join(columns)}) VALUES ({placeholders})"
    with _connect(db_path) as conn:
        conn.execute(sql, tuple(fields[column] for column in columns))


def update_run(db_path: Path, run_id: str, **fields: Any) -> None:
    if not fields:
        return
    updates = dict(fields)
    metadata = updates.pop("metadata", None)
    if metadata is not None:
        updates["metadata_json"] = _metadata_json(metadata)
    if "status" in updates:
        _validate_status(str(updates["status"]))
    allowed = {
        "updated_at",
        "started_at",
        "ended_at",
        "status",
        "cwd",
        "repo_root",
        "branch",
        "label",
        "command",
        "prompt",
        "output_dir",
        "stdout_path",
        "stderr_path",
        "result_path",
        "summary_path",
        "exit_code",
        "duration_ms",
        "error_message",
        "metadata_json",
    }
    unknown = sorted(set(updates) - allowed)
    if unknown:
        raise StorageError(f"unknown run update fields: {', '.join(unknown)}")
    updates.setdefault("updated_at", utc_now_iso())
    for key in (
        "cwd",
        "repo_root",
        "output_dir",
        "stdout_path",
        "stderr_path",
        "result_path",
        "summary_path",
    ):
        if key in updates:
            updates[key] = _path_or_none(updates[key])
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = [updates[key] for key in updates]
    values.append(run_id)
    with _connect(db_path) as conn:
        conn.execute(f"UPDATE runs SET {assignments} WHERE id = ?", values)


def add_run_event(
    db_path: Path,
    *,
    run_id: str,
    message: str,
    level: str | None = None,
    created_at: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO run_events (run_id, created_at, level, message, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, created_at or utc_now_iso(), level, message, _metadata_json(metadata)),
        )


def list_runs(
    db_path: Path,
    *,
    limit: int = 20,
    status: str | None = None,
    branch: str | None = None,
    label: str | None = None,
) -> list[RunRow]:
    clauses: list[str] = []
    values: list[Any] = []
    if status:
        clauses.append("status = ?")
        values.append(status)
    if branch:
        clauses.append("branch = ?")
        values.append(branch)
    if label:
        clauses.append("label = ?")
        values.append(label)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    values.append(limit)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM runs
            {where}
            ORDER BY COALESCE(started_at, created_at) DESC, created_at DESC, id DESC
            LIMIT ?
            """,
            values,
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def count_runs(db_path: Path) -> int:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM runs").fetchone()
    return int(row["count"] if row is not None else 0)


def backfill_from_output_dir(db_path: Path, output_root: Path) -> int:
    root = output_root.expanduser().resolve(strict=False)
    if not root.exists() or not root.is_dir():
        init_db(db_path)
        return 0
    imported = 0
    with _connect(db_path) as conn:
        for run_dir in sorted(root.iterdir()):
            if not run_dir.is_dir():
                continue
            record = _record_from_output_dir(run_dir)
            if record is None:
                continue
            exists = conn.execute(
                "SELECT 1 FROM runs WHERE output_dir = ? OR id = ? LIMIT 1",
                (record["output_dir"], record["id"]),
            ).fetchone()
            if exists is not None:
                continue
            columns = tuple(record.keys())
            placeholders = ", ".join("?" for _ in columns)
            conn.execute(
                f"INSERT OR IGNORE INTO runs ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(record[column] for column in columns),
            )
            imported += 1
    return imported


def mark_output_missing(
    db_path: Path,
    *,
    run_id: str | None = None,
    output_dir: str | Path | None = None,
) -> None:
    if run_id is None and output_dir is None:
        raise StorageError("run_id or output_dir is required")
    column = "id" if run_id is not None else "output_dir"
    value = run_id if run_id is not None else _path_or_none(output_dir)
    with _connect(db_path) as conn:
        row = conn.execute(
            f"SELECT metadata_json FROM runs WHERE {column} = ? LIMIT 1",
            (value,),
        ).fetchone()
        if row is None:
            return
        metadata = _load_metadata(row["metadata_json"])
        metadata["output_missing"] = True
        conn.execute(
            f"UPDATE runs SET updated_at = ?, metadata_json = ? WHERE {column} = ?",
            (utc_now_iso(), _metadata_json(metadata), value),
        )


def delete_db(db_path: Path) -> list[Path]:
    resolved = _absolute_path(db_path)
    deleted: list[Path] = []
    for path in (resolved, Path(f"{resolved}-wal"), Path(f"{resolved}-shm")):
        if path.exists():
            if path.is_symlink():
                path.unlink()
                deleted.append(path)
                continue
            if path.is_dir():
                raise StorageError(f"refusing to delete database path because it is a directory: {path}")
            path.unlink()
            deleted.append(path)
    return deleted


def format_storage_error(exc: BaseException, db_path: Path | None = None) -> str:
    location = f" at {db_path}" if db_path is not None else ""
    message = str(exc)
    lower = message.lower()
    if isinstance(exc, StorageError):
        return message
    if isinstance(exc, PermissionError) or "readonly" in lower or "permission" in lower:
        return f"SQLite index{location} is not writable: {message}"
    if "locked" in lower or "busy" in lower:
        return f"SQLite index{location} is locked; retry after the active run finishes: {message}"
    if "unable to open database file" in lower:
        return f"SQLite index{location} could not be opened; check the path and permissions: {message}"
    if isinstance(exc, sqlite3.DatabaseError):
        return f"SQLite index{location} failed: {message}"
    return f"SQLite index{location} failed: {message}"


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    resolved = init_db(db_path)
    conn = _open_connection(resolved)
    try:
        yield conn
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise StorageError(format_storage_error(exc, resolved)) from exc
    finally:
        conn.close()


def _open_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_db_parent(db_path: Path) -> None:
    if db_path.exists() and db_path.is_dir():
        raise StorageError(f"database path is a directory: {db_path}")
    if db_path.is_symlink():
        raise StorageError(f"database path is a symlink: {db_path}")
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageError(format_storage_error(exc, db_path)) from exc


def _absolute_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return Path.cwd() / expanded


def _migrate(conn: sqlite3.Connection) -> None:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise StorageError(
            f"database schema version {version} is newer than supported version {SCHEMA_VERSION}"
        )
    _create_schema(conn)
    if version < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            ended_at TEXT,
            status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'success', 'failed', 'cancelled')),
            cwd TEXT,
            repo_root TEXT,
            branch TEXT,
            label TEXT,
            command TEXT,
            prompt TEXT,
            output_dir TEXT,
            stdout_path TEXT,
            stderr_path TEXT,
            result_path TEXT,
            summary_path TEXT,
            exit_code INTEGER,
            duration_ms INTEGER,
            error_message TEXT,
            metadata_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            level TEXT,
            message TEXT NOT NULL,
            metadata_json TEXT,
            FOREIGN KEY(run_id) REFERENCES runs(id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(COALESCE(started_at, created_at))"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_branch ON runs(branch)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_label ON runs(label)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_output_dir_unique "
        "ON runs(output_dir) WHERE output_dir IS NOT NULL"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id)")


def _record_from_output_dir(run_dir: Path) -> RunRow | None:
    manifest_path = run_dir / "manifest.json"
    summary_path = run_dir / "run-summary.json"
    manifest = _read_json_object(manifest_path)
    summary = _read_json_object(summary_path)
    if manifest is None and summary is None:
        return None

    manifest_data = manifest or {}
    summary_data = summary or {}
    run_id = _string_or_none(manifest_data.get("run_id")) or _string_or_none(
        summary_data.get("run_id")
    ) or run_dir.name
    repo = _dict_or_empty(manifest_data.get("repo") or summary_data.get("repo"))
    output_dir = _string_or_none(manifest_data.get("output_dir")) or _string_or_none(
        summary_data.get("output_dir")
    ) or str(run_dir.resolve(strict=False))
    created_at = _string_or_none(manifest_data.get("created_at")) or _mtime_iso(run_dir)
    candidates = summary_data.get("candidates")
    if not isinstance(candidates, list):
        candidates = []
    started_at = _candidate_time(candidates, "started_at", min)
    ended_at = _candidate_time(candidates, "completed_at", max)
    status = _backfilled_status(summary_data, manifest_data)
    duration_ms = _duration_ms(started_at, ended_at)
    metadata = {
        "backfilled": True,
        "manifest_path": str(manifest_path) if manifest_path.exists() else None,
        "summary_path": str(summary_path) if summary_path.exists() else None,
        "candidate_count": len(candidates),
    }
    return {
        "id": run_id,
        "created_at": created_at,
        "updated_at": ended_at or created_at,
        "started_at": started_at,
        "ended_at": ended_at,
        "status": status,
        "cwd": _string_or_none(repo.get("path")),
        "repo_root": _string_or_none(repo.get("path")),
        "branch": _string_or_none(repo.get("base_ref")),
        "label": _string_or_none(manifest_data.get("label") or summary_data.get("label")),
        "command": None,
        "prompt": None,
        "output_dir": str(Path(output_dir).expanduser().resolve(strict=False)),
        "stdout_path": None,
        "stderr_path": None,
        "result_path": None,
        "summary_path": str(summary_path) if summary_path.exists() else None,
        "exit_code": 0 if status == "success" else 1 if status == "failed" else None,
        "duration_ms": duration_ms,
        "error_message": None,
        "metadata_json": _metadata_json(metadata),
    }


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _backfilled_status(summary: Mapping[str, Any], manifest: Mapping[str, Any]) -> str:
    passed = summary.get("passed")
    if passed is True:
        return "success"
    if passed is False:
        return "failed"
    candidates = manifest.get("candidates")
    if isinstance(candidates, list) and candidates:
        statuses = {
            str(item.get("status"))
            for item in candidates
            if isinstance(item, dict) and item.get("status") is not None
        }
        if statuses and statuses <= {"passed", "success", "completed"}:
            return "success"
        if "failed" in statuses:
            return "failed"
    return "pending"


def _candidate_time(candidates: list[Any], key: str, chooser: Any) -> str | None:
    values = [
        str(item[key])
        for item in candidates
        if isinstance(item, dict) and isinstance(item.get(key), str) and item.get(key)
    ]
    if not values:
        return None
    return chooser(values)


def _duration_ms(started_at: str | None, ended_at: str | None) -> int | None:
    if not started_at or not ended_at:
        return None
    try:
        started = datetime.fromisoformat(started_at)
        ended = datetime.fromisoformat(ended_at)
    except ValueError:
        return None
    return max(0, int((ended - started).total_seconds() * 1000))


def _mtime_iso(path: Path) -> str:
    try:
        timestamp = path.stat().st_mtime
    except OSError:
        return utc_now_iso()
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")


def _row_to_dict(row: sqlite3.Row) -> RunRow:
    return {key: row[key] for key in row.keys()}


def _metadata_json(metadata: Mapping[str, Any] | None) -> str | None:
    if metadata is None:
        return None
    cleaned = {key: value for key, value in metadata.items() if value is not None}
    return json.dumps(cleaned, sort_keys=True, ensure_ascii=False)


def _load_metadata(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {"previous_metadata_json": value}
    return loaded if isinstance(loaded, dict) else {"previous_metadata_json": value}


def _path_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Path):
        return str(value.expanduser().resolve(strict=False))
    return str(value)


def _validate_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise StorageError(
            f"invalid run status {status!r}; expected one of {', '.join(sorted(VALID_STATUSES))}"
        )


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _dict_or_empty(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
