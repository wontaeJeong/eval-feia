from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

import httpx
from rich.console import Console

from .errors import ErrorRecord
from .opencode_client import OpencodeClient


EVENT_STREAM_TIMEOUT = httpx.Timeout(5.0, read=0.5)


@dataclass(slots=True)
class ServerEvent:
    type: str
    data: Any
    raw_data: str


@dataclass(slots=True)
class ProgressStats:
    tool_call_count: int = 0
    token_input: int | None = None
    token_output: int | None = None
    token_reasoning: int | None = None
    cost_total: float | None = None
    _tool_call_ids: set[str] = field(default_factory=set)

    def record_tool_call(self, call_id: str | None) -> None:
        if not call_id:
            self.tool_call_count += 1
            return
        if call_id in self._tool_call_ids:
            return
        self._tool_call_ids.add(call_id)
        self.tool_call_count += 1

    def record_step_metrics(self, data: Any) -> None:
        properties = _properties(data)
        tokens = properties.get("tokens") if isinstance(properties, dict) else None
        if isinstance(tokens, dict):
            self.token_input = _sum_optional(self.token_input, _int_or_none(tokens.get("input")))
            self.token_output = _sum_optional(self.token_output, _int_or_none(tokens.get("output")))
            self.token_reasoning = _sum_optional(
                self.token_reasoning,
                _int_or_none(tokens.get("reasoning")),
            )
        if isinstance(properties, dict):
            self.cost_total = _sum_optional_float(self.cost_total, _float_or_none(properties.get("cost")))


@dataclass(slots=True)
class TrialProgressMetadata:
    index: int
    total: int
    trial_id: str
    label: str | None
    branch: str | None
    worktree: Path | None
    session_id: str | None = None

    def prefix(self) -> str:
        return f"[trial {self.index}/{self.total}]"

    def trial_details(self) -> str:
        if self.worktree is None:
            return ""
        return f"worktree={self.worktree}"


class TrialProgressLogger:
    def __init__(
        self,
        console: Console,
        metadata: TrialProgressMetadata,
        *,
        output_lock: threading.Lock,
        enabled: bool,
    ) -> None:
        self._console = console
        self._metadata = metadata
        self._output_lock = output_lock
        self._enabled = enabled
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._response: httpx.Response | None = None
        self._stats = ProgressStats()
        self._error: ErrorRecord | None = None
        self._stream_warning_printed = False

    @property
    def stats(self) -> ProgressStats:
        return self._stats

    @property
    def error(self) -> ErrorRecord | None:
        return self._error

    def started(self) -> None:
        details = self._metadata.trial_details()
        self.print(f"started {details}" if details else "started")

    def session_created(self, session_id: str) -> None:
        self._metadata.session_id = session_id
        self.print(f"session created session={session_id}")

    def completed(self, status: str, validation_status: str, elapsed_seconds: float) -> None:
        self.print(
            f"completed status={status} validation={validation_status} elapsed={elapsed_seconds:.3f}s"
        )

    def failed(self, error: ErrorRecord, elapsed_seconds: float) -> None:
        self.print(f"failed kind={error.kind} elapsed={elapsed_seconds:.3f}s")

    def print(self, message: str) -> None:
        if not self._enabled:
            return
        with self._output_lock:
            self._console.print(f"{self._metadata.prefix()} {message}", markup=False, soft_wrap=True)

    def start_event_stream(self, client: OpencodeClient, cwd: Path) -> None:
        if not self._enabled or not self._metadata.session_id:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._read_events,
            args=(client, cwd),
            name=f"eval-feia-progress-{self._metadata.trial_id}",
            daemon=True,
        )
        self._thread.start()

    def stop_event_stream(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        response = self._response
        if response is not None:
            response.close()
        self._thread.join(timeout=1.0)
        self._thread = None
        self._response = None

    def _read_events(self, client: OpencodeClient, cwd: Path) -> None:
        while not self._stop.is_set():
            try:
                with client.event_stream(cwd, timeout=EVENT_STREAM_TIMEOUT) as response:
                    self._response = response
                    for event in iter_sse_events(response.iter_lines()):
                        if self._stop.is_set():
                            return
                        if self._handle_event(event):
                            return
                return
            except httpx.ReadTimeout:
                continue
            except Exception as exc:
                if self._stop.is_set() and self._response is not None:
                    return
                self._warn_stream_disconnected(exc)
                return
            finally:
                self._response = None

    def _handle_event(self, event: ServerEvent) -> bool:
        session_id = extract_session_id(event.data)
        if session_id != self._metadata.session_id:
            return False

        message = format_progress_event(event)
        if message:
            self.print(message)
        if event.type == "session.error" or event.type == "session.next.step.failed":
            self._error = ErrorRecord(
                "session_error",
                _event_error_message(event.data) or "opencode session reported an error",
                details={"event_type": event.type},
            )
            return True
        if event.type == "session.idle":
            return True
        if event.type == "session.next.tool.called":
            properties = _properties(event.data)
            self._stats.record_tool_call(_string_or_none(properties.get("callID")))
        if event.type == "session.next.step.ended":
            self._stats.record_step_metrics(event.data)
        return False

    def _warn_stream_disconnected(self, exc: BaseException | None) -> None:
        if self._stream_warning_printed:
            return
        self._stream_warning_printed = True
        reason = f": {exc}" if exc is not None else ""
        with self._output_lock:
            self._console.print(
                f"{self._metadata.prefix()}[progress] event stream disconnected{reason}; "
                "continuing without live progress",
                style="yellow",
                markup=False,
                soft_wrap=True,
            )


def iter_sse_events(lines: Iterable[str]) -> Iterator[ServerEvent]:
    event_type = "message"
    data_lines: list[str] = []
    for raw_line in lines:
        line = raw_line.rstrip("\r")
        if not line:
            event = _build_event(event_type, data_lines)
            if event is not None:
                yield event
            event_type = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_type = value or "message"
        elif field == "data":
            data_lines.append(value)
    event = _build_event(event_type, data_lines)
    if event is not None:
        yield event


def extract_session_id(data: Any) -> str | None:
    return _find_session_id(data, depth=0)


def format_progress_event(event: ServerEvent) -> str | None:
    properties = _properties(event.data)
    if event.type == "session.status":
        status = _session_status(properties.get("status"))
        return f"session status: {status}" if status else "session status changed"
    if event.type == "session.idle":
        return "session status: idle"
    if event.type == "session.error":
        message = _event_error_message(event.data)
        return f"session status: error {message}" if message else "session status: error"
    if event.type == "session.diff":
        return "diff updated"
    if event.type == "file.edited":
        file_name = _string_or_none(properties.get("file"))
        return f"file edited: {file_name}" if file_name else "file edited"
    if event.type in {"permission.updated", "question.asked"}:
        request_id = _string_or_none(properties.get("permissionID") or properties.get("requestID"))
        return f"permission waiting: {request_id}" if request_id else "permission waiting"
    if event.type in {"permission.replied", "question.replied"}:
        return "permission replied"
    if event.type == "todo.updated":
        return "todo updated"
    if event.type == "session.next.step.started":
        agent = _string_or_none(properties.get("agent"))
        return f"step started: {agent}" if agent else "step started"
    if event.type == "session.next.step.ended":
        finish = _string_or_none(properties.get("finish"))
        return f"step ended: {finish}" if finish else "step ended"
    if event.type == "session.next.step.failed":
        message = _event_error_message(event.data)
        return f"step failed: {message}" if message else "step failed"
    if event.type == "session.next.retried":
        attempt = properties.get("attempt")
        return f"session status: retry attempt={attempt}" if attempt is not None else "session status: retry"
    if event.type == "session.next.tool.called":
        tool = _string_or_none(properties.get("tool"))
        return f"tool started: {tool}" if tool else "tool started"
    if event.type == "session.next.tool.success":
        return _tool_result("tool completed", properties)
    if event.type == "session.next.tool.failed":
        return _tool_result("tool failed", properties)
    if event.type == "message.part.updated":
        part = properties.get("part")
        if isinstance(part, dict) and part.get("type") == "tool":
            name = _string_or_none(part.get("name"))
            state = part.get("state")
            status = state.get("status") if isinstance(state, dict) else None
            details = " ".join(item for item in (name, _string_or_none(status)) if item)
            return f"tool updated: {details}" if details else "tool updated"
    return None


def _build_event(event_type: str, data_lines: list[str]) -> ServerEvent | None:
    if not data_lines:
        return None
    raw_data = "\n".join(data_lines)
    try:
        data = json.loads(raw_data)
    except json.JSONDecodeError:
        data = raw_data
    data_type = data.get("type") if isinstance(data, dict) else None
    resolved_type = data_type if isinstance(data_type, str) and data_type else event_type
    return ServerEvent(type=resolved_type, data=data, raw_data=raw_data)


def _properties(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        value = data.get("properties")
        if isinstance(value, dict):
            return value
        return data
    return {}


def _find_session_id(value: Any, *, depth: int) -> str | None:
    if depth > 5:
        return None
    if isinstance(value, dict):
        for key in ("sessionID", "sessionId", "session_id"):
            found = value.get(key)
            if isinstance(found, str) and found:
                return found
        for key in ("properties", "session", "message", "info", "part"):
            nested = value.get(key)
            found = _find_session_id(nested, depth=depth + 1)
            if found:
                return found
        for nested in value.values():
            found = _find_session_id(nested, depth=depth + 1)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_session_id(nested, depth=depth + 1)
            if found:
                return found
    return None


def _session_status(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        status = value.get("type") or value.get("status") or value.get("state")
        if isinstance(status, str):
            return status
    return None


def _event_error_message(data: Any) -> str | None:
    properties = _properties(data)
    error = properties.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("type") or error.get("name")
        return str(message) if message is not None else None
    if isinstance(error, str):
        return error
    message = properties.get("message")
    return str(message) if message is not None else None


def _tool_result(prefix: str, properties: dict[str, Any]) -> str:
    call_id = _string_or_none(properties.get("callID"))
    return f"{prefix}: {call_id}" if call_id else prefix


def _compact(value: str, limit: int = 80) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _sum_optional(current: int | None, value: int | None) -> int | None:
    if value is None:
        return current
    return (current or 0) + value


def _sum_optional_float(current: float | None, value: float | None) -> float | None:
    if value is None:
        return current
    return (current or 0.0) + value
