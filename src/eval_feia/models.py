from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


DEFAULT_PROMPT = "웹 검색 후 Knox 메일 리포트 에이전트 작성"
DEFAULT_SKILL = "impl"
DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_OPENCODE_VERSION = "1.4.6"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, StrEnum):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    return value


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CLEANUP = "cleanup"


class RunPhase(StrEnum):
    QUEUED = "queued"
    WORKTREE = "worktree"
    SERVER_STARTING = "server-starting"
    SERVER_HEALTH = "server-health"
    CWD_CHECK = "cwd-check"
    SERVER_INFO = "server-info"
    SERVER_READY = "server-ready"
    SESSION_CREATE = "session-create"
    SSE_CONNECT = "sse-connect"
    PROMPT_SEND = "prompt-send"
    RUNNING = "running"
    IDLE_WAIT = "idle-wait"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CLEANUP = "cleanup"
    SERVER_MISMATCH = "server-mismatch"
    SERVER_STOPPING = "server-stopping"
    SERVER_RESTARTING = "server-restarting"
    SERVER_RESTART_EXHAUSTED = "server-restart-exhausted"


class FailureClass(StrEnum):
    NONE = "none"
    AGENT_FAILURE = "agent_failure"
    VALIDATION_FAILURE = "validation_failure"
    SERVER_UNHEALTHY = "server_unhealthy"
    SERVER_VERSION_MISMATCH = "server_version_mismatch"
    CWD_MISMATCH = "cwd_mismatch"
    SERVER_RESTART_EXHAUSTED = "server_restart_exhausted"
    TIMEOUT = "timeout"
    HARNESS_ERROR = "harness_error"


class VersionCheck(StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


class CwdCheckStatus(StrEnum):
    OK = "ok"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"
    SKIPPED = "skipped"


@dataclass(slots=True)
class RunConfig:
    repo: Path
    count: int = 20
    concurrency: int = 1
    prompt: str = DEFAULT_PROMPT
    prompt_file: Path | None = None
    skill: str = DEFAULT_SKILL
    branch: str = "HEAD"
    worktree_root: Path | None = None
    output_dir: Path = Path("results")
    base_port: int = 4096
    opencode_version: str = DEFAULT_OPENCODE_VERSION
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    server_start_timeout_seconds: float = 30.0
    health_poll_interval_seconds: float = 0.5
    cwd_check: bool = True
    restart_on_mismatch: bool = True
    max_server_restarts: int = 2
    idle_quiet_seconds: float = 2.0
    hard_timeout_seconds: float = 1800.0
    no_live: bool = False
    json: bool = False
    fake_server_url: str | None = None


@dataclass(slots=True)
class WorktreeInfo:
    path: str
    base_ref: str
    base_commit: str
    created_at: str = field(default_factory=now_iso)


@dataclass(slots=True)
class BatchManifest:
    batch_id: str
    created_at: str
    repo: str
    base_ref: str
    base_commit: str
    opencode_version: str
    worktree_root: str | None = None
    runs: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ServerHealth:
    healthy: bool
    reported_version: str | None
    checked_at: str = field(default_factory=now_iso)
    elapsed_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CwdCheckResult:
    expected_cwd: str
    actual_cwd: str | None
    status: CwdCheckStatus
    source: str | None = None
    checked_at: str = field(default_factory=now_iso)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ServerInfo:
    run_id: str
    pid: int | None
    hostname: str
    port: int
    base_url: str
    health_url: str
    requested_version: str
    reported_version: str | None
    version_check: VersionCheck
    expected_cwd: str
    actual_cwd: str | None
    cwd_check: CwdCheckStatus
    restart_count: int
    server_start_elapsed_ms: int = 0


@dataclass(slots=True)
class RestartHistoryEntry:
    attempt: int
    pid: int | None
    reason: str
    requested_version: str
    reported_version: str | None
    expected_cwd: str
    actual_cwd: str | None
    terminated: bool
    killed: bool
    elapsed_ms: int


@dataclass(slots=True)
class LiveSummary:
    sse_endpoint: str | None = None
    sse_listener_started_at: str | None = None
    sse_connected_at: str | None = None
    prompt_sent_at: str | None = None
    first_event_at: str | None = None
    last_event_at: str | None = None
    total_sse_events: int = 0
    sse_parser_errors: int = 0
    total_status_polls: int = 0
    total_children_polls: int = 0
    total_todo_polls: int = 0
    renderer_refresh_count: int = 0
    final_phase: str = RunPhase.QUEUED


@dataclass(slots=True)
class Metrics:
    total_messages: int = 0
    user_message_count: int = 0
    assistant_message_count: int = 0
    total_tool_calls: int = 0
    tool_call_success_count: int = 0
    tool_call_failure_count: int = 0
    total_subagent_run: int = 0
    max_session_depth: int = 0
    total_todo_items: int = 0
    todo_completed_count: int = 0
    todo_failed_count: int = 0
    total_operational_ms: int = 0
    server_start_elapsed_ms: int = 0
    idle_quiet_ms: int = 0
    validation_retries: int = 0
    validation_failures: int = 0
    server_restart_count: int = 0
    server_ready: bool = False
    prompt_sent: bool = False
    opencode_completed: bool = False
    timeout: bool = False
    harness_error: bool = False
    artifact_found: bool = False
    json_parse_ok: bool = False
    autogen_load_ok: bool | None = None
    validation_passed: bool = False
    task_success: bool = False


@dataclass(slots=True)
class ValidationResult:
    artifact_found: bool = False
    artifact_path: str | None = None
    json_parse_ok: bool = False
    schema_ok: bool = False
    autogen_load_ok: bool | None = None
    secret_scan_ok: bool = True
    task_requirements_ok: bool = False
    validation_passed: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RunRecord:
    run_id: str
    batch_id: str
    status: RunStatus = RunStatus.QUEUED
    failure_class: FailureClass = FailureClass.NONE
    worktree: WorktreeInfo | None = None
    server_health: ServerHealth | None = None
    cwd_check: CwdCheckResult | None = None
    server_info: ServerInfo | None = None
    server_restart_history: list[RestartHistoryEntry] = field(default_factory=list)
    live_summary: LiveSummary = field(default_factory=LiveSummary)
    metrics: Metrics = field(default_factory=Metrics)
    validation: ValidationResult = field(default_factory=ValidationResult)
    error_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = to_jsonable(self)
        for key in ("worktree", "server_health", "cwd_check", "server_info"):
            if data[key] is None:
                data[key] = {}
        return data
