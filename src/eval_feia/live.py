from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from rich.console import Console
from rich.live import Live
from rich.table import Table

from .models import RunPhase
from .reports import JSONLRenderer


@dataclass(slots=True)
class LiveState:
    run_id: str
    port: int | None = None
    phase: str = RunPhase.QUEUED
    health: str = ""
    cwd: str = ""
    message_count: int = 0
    tool_call_count: int = 0
    child_session_count: int = 0
    todo_status: str = ""
    quiet_seconds: float = 0.0
    started_at: float = field(default_factory=time.monotonic)
    note: str = ""
    restart_count: int = 0
    worktree_path: str | None = None

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)

    def to_progress_event(self) -> dict[str, Any]:
        return {
            "type": "run_progress",
            "run_id": self.run_id,
            "phase": str(self.phase),
            "msg": self.message_count,
            "tool": self.tool_call_count,
            "child": self.child_session_count,
            "todo": self.todo_status,
            "quiet": int(self.quiet_seconds),
            "elapsed_ms": int(self.elapsed_seconds * 1000),
        }


class LiveStateStore:
    def __init__(self) -> None:
        self.states: dict[str, LiveState] = {}

    def get(self, run_id: str) -> LiveState:
        if run_id not in self.states:
            self.states[run_id] = LiveState(run_id=run_id)
        return self.states[run_id]

    def update_from_sse(self, run_id: str, event_type: str | None, data: Any) -> LiveState:
        state = self.get(run_id)
        combined = f"{event_type or ''} {data.get('type', '') if isinstance(data, dict) else ''}".lower()
        if "message" in combined:
            state.message_count += 1
        if "tool" in combined:
            state.tool_call_count += 1
        if "session" in combined or "subagent" in combined or "child" in combined:
            state.child_session_count = max(state.child_session_count, 1)
        return state

    def update_from_polls(
        self,
        run_id: str,
        status: Any | None = None,
        children: Any | None = None,
        todo: Any | None = None,
    ) -> LiveState:
        state = self.get(run_id)
        if isinstance(children, list):
            state.child_session_count = len(children)
        elif isinstance(children, dict):
            value = children.get("children") or children.get("sessions") or []
            if isinstance(value, list):
                state.child_session_count = len(value)
        if todo is not None:
            items = todo.get("items") if isinstance(todo, dict) else todo
            if isinstance(items, list):
                states = [str(item.get("status", "")) for item in items if isinstance(item, dict)]
                state.todo_status = "done" if states and all(s in {"completed", "done"} for s in states) else "running"
            elif isinstance(todo, dict):
                state.todo_status = str(todo.get("status", ""))
        if isinstance(status, dict):
            raw_phase = status.get("phase") or status.get("status")
            if raw_phase:
                state.note = str(raw_phase)[:32]
        return state

    def all_idle(self, statuses: Any, children: Any) -> bool:
        return _idle(statuses) and _idle(children)


def _idle(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, list):
        return all(_idle(item) for item in value)
    if isinstance(value, dict):
        if "children" in value:
            return _idle(value["children"])
        if "sessions" in value:
            return _idle(value["sessions"])
        status = str(value.get("status") or value.get("phase") or value.get("state") or "").lower()
        if status:
            return status in {"idle", "completed", "done", "finished"}
    return True


def make_live_table(states: Iterable[LiveState]) -> Table:
    table = Table()
    for column in ["Run", "Port", "Phase", "Health", "CWD", "Msg", "Tool", "Child", "Todo", "Quiet", "Elapsed", "Note"]:
        table.add_column(column, overflow="ellipsis", no_wrap=True)
    for state in states:
        table.add_row(
            state.run_id,
            "" if state.port is None else str(state.port),
            str(state.phase),
            state.health,
            state.cwd,
            str(state.message_count),
            str(state.tool_call_count),
            str(state.child_session_count),
            state.todo_status,
            str(int(state.quiet_seconds)),
            str(int(state.elapsed_seconds)),
            state.note[:24],
        )
    return table


class RichLiveRenderer:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self.refresh_count = 0

    def render_once(self, states: Iterable[LiveState]) -> None:
        self.console.print(make_live_table(states))
        self.refresh_count += 1

    def live(self, states: Iterable[LiveState]) -> Live:
        return Live(make_live_table(states), console=self.console, refresh_per_second=4)


__all__ = ["JSONLRenderer", "LiveState", "LiveStateStore", "RichLiveRenderer", "make_live_table"]
