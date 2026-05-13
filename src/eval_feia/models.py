from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast


DEFAULT_PROMPT = "웹 검색 후 Knox 메일 리포트 에이전트 작성"
DEFAULT_SKILL = "impl"

FailureClass = Literal[
    "none",
    "agent_failure",
    "validation_failure",
    "server_unhealthy",
    "server_version_mismatch",
    "cwd_mismatch",
    "server_restart_exhausted",
    "timeout",
    "harness_error",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(cast(Any, value)))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


@dataclass(slots=True)
class BatchSpec:
    repo: Path
    count: int = 20
    concurrency: int = 1
    prompt: str = DEFAULT_PROMPT
    skill: str = DEFAULT_SKILL
    branch: str = "HEAD"
    worktree_root: Path | None = None
    output_dir: Path = Path("results")
    base_port: int = 4096
    opencode_version: str = "1.4.6"
    provider: str | None = None
    model: str | None = None
    server_start_timeout_seconds: float = 60.0
    health_poll_interval_seconds: float = 1.0
    cwd_check: bool = True
    restart_on_mismatch: bool = True
    max_server_restarts: int = 2
    idle_quiet_seconds: float = 10.0
    hard_timeout_seconds: float = 1800.0
    live: bool = True
    json: bool = False
    batch_id: str | None = None


@dataclass(slots=True)
class RunSpec:
    batch_id: str
    run_id: str
    repo: Path
    branch: str
    base_commit: str
    prompt: str
    skill: str
    output_dir: Path
    batch_dir: Path
    run_dir: Path
    temp_run_dir: Path
    worktree_path: Path
    home_dir: Path
    tmp_dir: Path
    port: int
    opencode_version: str
    provider: str | None
    model: str | None
    server_start_timeout_seconds: float
    health_poll_interval_seconds: float
    cwd_check: bool
    restart_on_mismatch: bool
    max_server_restarts: int
    idle_quiet_seconds: float
    hard_timeout_seconds: float


@dataclass(slots=True)
class WorktreeInfo:
    path: str = ""
    base_ref: str = ""
    base_commit: str = ""
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class HealthCheck:
    ok: bool = False
    healthy: bool = False
    version: str = "unknown"
    attempts: int = 0
    elapsed_ms: int = 0
    error: str | None = None


@dataclass(slots=True)
class CwdCheck:
    result: str = "unknown"
    expected_cwd: str = ""
    actual_cwd: str | None = None
    source: str | None = None
    error: str | None = None


@dataclass(slots=True)
class ServerInfo:
    run_id: str
    pid: int | None
    hostname: str
    port: int
    base_url: str
    health_url: str
    requested_version: str
    reported_version: str
    version_check: str
    expected_cwd: str
    actual_cwd: str | None
    cwd_check: str
    restart_count: int
    server_start_elapsed_ms: int = 0


@dataclass(slots=True)
class LiveSummary:
    sse_endpoint: str = "/global/event"
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
    final_phase: str = "queued"


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
    secret_scan_ok: bool = False
    task_requirements_ok: bool = False
    validation_passed: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RunRecord:
    run_id: str
    batch_id: str
    status: str = "queued"
    failure_class: FailureClass = "none"
    error_message: str | None = None
    worktree: WorktreeInfo = field(default_factory=WorktreeInfo)
    server_health: HealthCheck = field(default_factory=HealthCheck)
    cwd_check: CwdCheck = field(default_factory=CwdCheck)
    server_info: dict[str, Any] = field(default_factory=dict)
    server_restart_history: list[dict[str, Any]] = field(default_factory=list)
    live_summary: LiveSummary = field(default_factory=LiveSummary)
    metrics: Metrics = field(default_factory=Metrics)
    validation: ValidationResult = field(default_factory=ValidationResult)
    prompt_sent: bool = False
    session_id: str | None = None
    temp_run_dir: str = ""
    started_at: str = field(default_factory=utc_now_iso)
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(slots=True)
class ProgressEvent:
    type: str
    run_id: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        payload = {"type": self.type, "run_id": self.run_id, "ts": self.ts}
        payload.update(jsonable(self.data))
        return payload
