from __future__ import annotations

from typing import Any, NotRequired, TypeAlias, TypedDict


JsonValue: TypeAlias = None | bool | int | float | str | list[Any] | dict[str, Any]
JsonObject: TypeAlias = dict[str, Any]


class ValidationCommandResult(TypedDict):
    name: str
    command: str
    cwd: str
    started_at: str
    completed_at: str
    exit_code: int
    timeout: bool
    stdout_file: str
    stderr_file: str
    required: bool


class ValidationResult(TypedDict):
    commands: list[ValidationCommandResult]
    passed: bool


class CandidateSummary(TypedDict):
    files_changed: int
    additions: int
    deletions: int
    token_input: int | None
    token_output: int | None
    token_reasoning: int | None
    tool_call_count: int | None
    tool_success_count: int | None
    tool_error_count: int | None
    cost_total: float | None
    final_output_file: str


class OpencodeArtifactFiles(TypedDict):
    session: str
    messages: str
    children: str
    todo: str
    diff: str
    file_status: str


class LocalArtifactFiles(TypedDict):
    git_status: str
    git_diff: str
    validation: str


class CandidateResult(TypedDict):
    candidate_id: str
    base_ref: str
    base_sha: str
    branch_name: str | None
    status: str
    worktree_path: str
    session_id: str | None
    started_at: str
    completed_at: str
    duration_seconds: float
    validation_status: str
    opencode: OpencodeArtifactFiles
    local: LocalArtifactFiles
    summary: CandidateSummary
    collection_errors: list[JsonObject]
    error: JsonObject | None
    eval_id: NotRequired[str]
    requested_branch_name: NotRequired[str]


class RunSummary(TypedDict):
    run_id: str
    label: str | None
    server: JsonObject
    opencode_version: str | None
    repo: JsonObject
    output_dir: str
    passed: bool
    health: JsonObject
    candidates: list[CandidateResult]
