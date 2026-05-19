from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RepoRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Path
    base_ref: str
    base_sha: str


class ServerRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    version: str | None = None


class CandidateManifestRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    eval_id: str | None = None
    requested_branch_name: str | None = None
    branch_name: str | None = None
    worktree_path: Path
    result_dir: Path
    session_id: str | None = None
    status: str = "created"

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_label(cls, value: object) -> object:
        if isinstance(value, dict) and "label" in value:
            cleaned = dict(value)
            cleaned.pop("label", None)
            return cleaned
        return value


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    run_id: str
    label: str | None = None
    created_at: str
    repo: RepoRecord
    server: ServerRecord
    output_dir: Path
    worktree_root: Path
    candidates: list[CandidateManifestRecord] = Field(default_factory=list)

    def upsert_candidate(self, record: CandidateManifestRecord) -> None:
        for index, existing in enumerate(self.candidates):
            if existing.id == record.id:
                self.candidates[index] = record
                return
        self.candidates.append(record)

    def candidate(self, candidate_id: str) -> CandidateManifestRecord | None:
        for record in self.candidates:
            if record.id == candidate_id:
                return record
        return None


def utc_now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_manifest(manifest: Manifest, path: Path | None = None) -> Path:
    manifest_path = path or manifest.output_dir / "manifest.json"
    _write_text_atomic(manifest_path, _json_dumps(manifest.model_dump(mode="json", exclude_none=True)))
    return manifest_path


def load_manifest(path: Path) -> Manifest:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return Manifest.model_validate(data)


def write_json(path: Path, value: Any) -> None:
    _write_text_atomic(path, _json_dumps(_jsonable(value)))


def _write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(value, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _json_dumps(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value
