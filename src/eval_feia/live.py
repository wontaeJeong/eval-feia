from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO

from rich.console import Console
from rich.live import Live
from rich.table import Table

from .models import ProgressEvent, jsonable


@dataclass(slots=True)
class LiveRunState:
    run_id: str
    port: int = 0
    phase: str = "queued"
    health: str = "-"
    cwd: str = "-"
    message_count: int = 0
    tool_call_count: int = 0
    child_session_count: int = 0
    todo_status: str = "-"
    quiet_seconds: float = 0.0
    start_time: float = field(default_factory=time.monotonic)
    note: str = ""
    restart_count: int = 0
    worktree_path: str = ""
    last_activity: float = field(default_factory=time.monotonic)

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.start_time)

    def apply_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", event.get("event", ""))).lower()
        properties = event.get("properties")
        payload: dict[str, Any] = properties if isinstance(properties, dict) else event
        if "message" in event_type or event_type in {"user", "assistant"}:
            self.message_count += 1
            self.last_activity = time.monotonic()
        if "tool" in event_type:
            self.tool_call_count += 1
            self.last_activity = time.monotonic()
        if "session" in event_type and ("child" in event_type or "sub" in event_type):
            self.child_session_count += 1
            self.last_activity = time.monotonic()
        if "todo" in event_type:
            status = payload.get("status") or payload.get("state") or event.get("status")
            if status:
                self.todo_status = str(status)[:16]
            self.last_activity = time.monotonic()

    def update_from_status(self, status: Any) -> None:
        active = has_active_status(status)
        if active:
            self.last_activity = time.monotonic()
            self.phase = "running"
        self.quiet_seconds = max(0.0, time.monotonic() - self.last_activity)

    def update_children(self, children: Any) -> None:
        if isinstance(children, list):
            self.child_session_count = len(children)
            if any(has_active_status(child) for child in children):
                self.last_activity = time.monotonic()

    def update_todo(self, todo: Any) -> None:
        if isinstance(todo, list):
            if not todo:
                self.todo_status = "none"
                return
            done = sum(1 for item in todo if str(item.get("status", item.get("state", ""))).lower() in {"done", "completed", "complete"}) if all(isinstance(item, dict) for item in todo) else 0
            self.todo_status = f"{done}/{len(todo)}"
            if done < len(todo):
                self.last_activity = time.monotonic()


def has_active_status(value: Any) -> bool:
    if isinstance(value, dict):
        candidates = [value.get("status"), value.get("state"), value.get("phase")]
        if any(str(item).lower() in {"running", "busy", "active", "pending", "queued"} for item in candidates if item is not None):
            return True
        return any(has_active_status(item) for item in value.values())
    if isinstance(value, list):
        return any(has_active_status(item) for item in value)
    return False


def is_idle(status: Any, children: Any, quiet_seconds: float, idle_quiet_seconds: float, recent_events: bool = False) -> bool:
    return (
        quiet_seconds >= idle_quiet_seconds
        and not recent_events
        and not has_active_status(status)
        and not has_active_status(children)
    )


class JsonlWriter:
    def __init__(self, path: Path | None = None, stream: TextIO | None = None) -> None:
        self.path = path
        self.stream = stream
        self._owned: TextIO | None = None
        if stream is None:
            if path is None:
                self.stream = sys.stdout
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                self._owned = path.open("a", encoding="utf-8", buffering=1)
                self.stream = self._owned

    def write(self, obj: dict[str, Any] | ProgressEvent) -> None:
        payload = obj.to_dict() if isinstance(obj, ProgressEvent) else jsonable(obj)
        assert self.stream is not None
        self.stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.stream.flush()

    def close(self) -> None:
        if self._owned is not None:
            self._owned.close()

    def __enter__(self) -> JsonlWriter:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class ProgressSink:
    def emit(self, event: ProgressEvent) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class NullProgressSink(ProgressSink):
    def emit(self, event: ProgressEvent) -> None:
        return


class JsonProgressSink(ProgressSink):
    def __init__(self, writer: JsonlWriter | None = None) -> None:
        self.writer = writer or JsonlWriter()

    def emit(self, event: ProgressEvent) -> None:
        self.writer.write(event)


class RichProgressSink(ProgressSink):
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def emit(self, event: ProgressEvent) -> None:
        payload = event.to_dict()
        kind = payload.get("type", "event")
        run_id = payload.get("run_id", "-")
        if kind == "worktree_created":
            self.console.print(f"{run_id} | worktree | {payload.get('path', '')}")
        elif kind == "server_info":
            self.console.print(
                f"{run_id} | server_info | pid={payload.get('pid')} port={payload.get('port')} url={payload.get('base_url')}"
            )
            self.console.print(
                f"{run_id} | server_info | req={payload.get('requested_version')} actual={payload.get('reported_version')} check={payload.get('version_check')}"
            )
            self.console.print(
                f"{run_id} | server_info | expected={payload.get('expected_cwd')} actual={payload.get('actual_cwd')} cwd={payload.get('cwd_check')} restarts={payload.get('restart_count')}"
            )
        else:
            self.console.print(f"{run_id} | {kind} | {payload.get('phase', payload.get('note', ''))}")


class RenderingProgressSink(ProgressSink):
    def __init__(self, inner: ProgressSink, renderer: RichLiveRenderer) -> None:
        self.inner = inner
        self.renderer = renderer
        self._lock = threading.Lock()

    def emit(self, event: ProgressEvent) -> None:
        with self._lock:
            self.inner.emit(event)
            self.renderer.update()


def build_table(states: list[LiveRunState]) -> Table:
    table = Table(title="eval-feia", expand=True)
    for column in ["Run", "Port", "Phase", "Health", "CWD", "Msg", "Tool", "Child", "Todo", "Quiet", "Elapsed", "Note"]:
        table.add_column(column, no_wrap=column != "Note")
    for state in states:
        table.add_row(
            state.run_id,
            str(state.port),
            state.phase[:18],
            state.health[:8],
            state.cwd[:8],
            str(state.message_count),
            str(state.tool_call_count),
            str(state.child_session_count),
            state.todo_status[:12],
            str(int(state.quiet_seconds)),
            str(int(state.elapsed_seconds)),
            state.note[:28],
        )
    return table


class RichLiveRenderer:
    def __init__(self, states: list[LiveRunState], console: Console | None = None) -> None:
        self.states = states
        self.console = console or Console()
        self.refresh_count = 0
        self._live: Live | None = None

    def __enter__(self) -> RichLiveRenderer:
        self._live = Live(build_table(self.states), console=self.console, refresh_per_second=2, transient=False, redirect_stdout=False, redirect_stderr=False)
        self._live.__enter__()
        return self

    def update(self) -> None:
        self.refresh_count += 1
        if self._live is not None:
            self._live.update(build_table(self.states), refresh=True)

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        if self._live is not None:
            self._live.__exit__(exc_type, exc, tb)
