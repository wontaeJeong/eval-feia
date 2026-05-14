from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    worktree_path: Path
    result_dir: Path
    session_id: str | None = None
    status: str = "created"


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    run_id: str
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
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(_json_dumps(manifest.model_dump(mode="json")), encoding="utf-8")
    return manifest_path


def load_manifest(path: Path) -> Manifest:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return Manifest.model_validate(data)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_dumps(_jsonable(value)), encoding="utf-8")


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
