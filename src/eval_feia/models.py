from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PROMPT = "웹 검색 후 Knox 메일 리포트 에이전트 작성"
DEFAULT_SKILL = "impl"
LOOPBACK_HOST = "127.0.0.1"


class FailureClass:
    NONE = "none"
    AGENT_FAILURE = "agent_failure"
    VALIDATION_FAILURE = "validation_failure"
    SERVER_UNHEALTHY = "server_unhealthy"
    SERVER_VERSION_MISMATCH = "server_version_mismatch"
    CWD_MISMATCH = "cwd_mismatch"
    SERVER_RESTART_EXHAUSTED = "server_restart_exhausted"
    TIMEOUT = "timeout"
    HARNESS_ERROR = "harness_error"
    ARTIFACT_FAILURE = "artifact_failure"
    DIFF_FAILURE = "diff_failure"
    LOG_FAILURE = "log_failure"
    TEST_FAILURE = "test_failure"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {field_info.name: json_safe(getattr(value, field_info.name)) for field_info in fields(value)}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    return value


@dataclass
class RunOptions:
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
    provider: str = "openai"
    model: str = "gpt-5.5"
    server_start_timeout_seconds: float = 30.0
    health_poll_interval_seconds: float = 0.5
    cwd_check: bool = True
    restart_on_mismatch: bool = True
    max_server_restarts: int = 2
    idle_quiet_seconds: float = 30.0
    hard_timeout_seconds: float = 1800.0
    no_live: bool = False
    json_output: bool = False
    remote_instrumentation_url: str | None = None
    fake_server_url: str | None = None


@dataclass
class WorktreeInfo:
    path: Path
    base_ref: str
    base_commit: str
    created_at: str = field(default_factory=now_iso)


@dataclass
class HealthCheck:
    ok: bool = False
    healthy: bool | None = None
    version: str | None = None
    elapsed_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class CwdCheck:
    expected_cwd: str
    actual_cwd: str | None = None
    result: str = "unknown"
    source: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ServerInfo:
    run_id: str
    pid: int
    hostname: str
    port: int
    base_url: str
    health_url: str
    requested_version: str
    reported_version: str | None
    version_check: str
    expected_cwd: str
    actual_cwd: str | None
    cwd_check: str
    restart_count: int
    server_start_elapsed_ms: int


@dataclass
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
    final_phase: str = "queued"


@dataclass
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
    agent_done: bool = False
    test_done: bool = False
    test_failed: bool = False
    artifact_done: bool = False
    diff_done: bool = False
    log_done: bool = False
    opencode_completed: bool = False
    timeout: bool = False
    harness_error: bool = False
    artifact_found: bool = False
    json_parse_ok: bool = False
    autogen_load_ok: bool | None = None
    validation_passed: bool = False
    task_success: bool = False


@dataclass
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


@dataclass
class RunRecord:
    run_id: str
    batch_id: str
    status: str = "queued"
    failure_class: str = FailureClass.NONE
    error_message: str | None = None
    worktree: WorktreeInfo | None = None
    server_health: HealthCheck | None = None
    cwd_check: CwdCheck | None = None
    server_info: ServerInfo | None = None
    server_restart_history: list[dict[str, Any]] = field(default_factory=list)
    live_summary: LiveSummary = field(default_factory=LiveSummary)
    metrics: Metrics = field(default_factory=Metrics)
    gates: dict[str, bool] = field(
        default_factory=lambda: {
            "prompt_sent": False,
            "agent_done": False,
            "test_done": False,
            "test_failed": False,
            "artifact_done": False,
            "diff_done": False,
            "log_done": False,
        }
    )
    validation: ValidationResult = field(default_factory=ValidationResult)
    started_at: str = field(default_factory=now_iso)
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return json_safe(self)
