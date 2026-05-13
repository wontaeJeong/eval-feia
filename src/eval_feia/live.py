# pyright: reportMissingImports=false
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, TextIO

from rich.console import Console
from rich.table import Table


class JsonlWriter:
    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self._lock = threading.Lock()

    def write(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.stream.write(line + "\n")
            self.stream.flush()


@dataclass(slots=True)
class LiveState:
    run_id: str
    port: int
    phase: str = "queued"
    health: str = "-"
    cwd: str = "-"
    message_count: int = 0
    tool_call_count: int = 0
    child_session_count: int = 0
    todo_status: str = "-"
    quiet_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    note: str = ""
    restart_count: int = 0
    worktree_path: str | None = None
    started_at: float = field(default_factory=time.monotonic)

    def set_phase(self, phase: str, note: str = "") -> None:
        self.phase = phase
        self.note = note

    def update_event(self, event: dict[str, Any]) -> None:
        payload = event.get("json")
        if isinstance(payload, dict) and "payload" in payload and isinstance(payload["payload"], dict):
            payload = payload["payload"]
        event_type = ""
        if isinstance(payload, dict):
            event_type = str(payload.get("type", ""))
        if "message" in event_type:
            self.message_count += 1
        if "tool" in event_type:
            self.tool_call_count += 1
        if "session" in event_type and ("child" in event_type or "created" in event_type):
            self.child_session_count += 1

    def update_status(self, status: dict[str, Any]) -> bool:
        active = False
        for value in status.values():
            if isinstance(value, dict) and value.get("type") != "idle":
                active = True
        return active

    def update_children(self, children: list[dict[str, Any]]) -> None:
        self.child_session_count = len(children)

    def update_todo(self, todo: list[dict[str, Any]]) -> None:
        if not todo:
            self.todo_status = "0"
            return
        completed = sum(1 for item in todo if str(item.get("status", "")).lower() in {"completed", "done"})
        self.todo_status = f"{completed}/{len(todo)}"

    def snapshot(self) -> dict[str, Any]:
        self.elapsed_seconds = time.monotonic() - self.started_at
        return {
            "run_id": self.run_id,
            "port": self.port,
            "phase": self.phase,
            "health": self.health,
            "cwd": self.cwd,
            "msg": self.message_count,
            "tool": self.tool_call_count,
            "child": self.child_session_count,
            "todo": self.todo_status,
            "quiet": round(self.quiet_seconds, 2),
            "elapsed_ms": int(self.elapsed_seconds * 1000),
            "note": self.note,
            "restart_count": self.restart_count,
            "worktree_path": self.worktree_path,
        }


def render_state_table(states: list[LiveState]) -> Table:
    table = Table("Run", "Port", "Phase", "Health", "CWD", "Msg", "Tool", "Child", "Todo", "Quiet", "Elapsed", "Note")
    for state in states:
        snapshot = state.snapshot()
        table.add_row(
            state.run_id,
            str(state.port),
            state.phase[:16],
            state.health[:8],
            state.cwd[:8],
            str(state.message_count),
            str(state.tool_call_count),
            str(state.child_session_count),
            state.todo_status[:8],
            str(snapshot["quiet"]),
            str(snapshot["elapsed_ms"]),
            state.note[:24],
        )
    return table


def render_snapshot_table(snapshots: list[dict[str, Any]]) -> Table:
    table = Table("Run", "Port", "Phase", "Health", "CWD", "Msg", "Tool", "Child", "Todo", "Quiet", "Elapsed", "Note")
    for snapshot in snapshots:
        table.add_row(
            str(snapshot.get("run_id", "-")),
            str(snapshot.get("port", "-")),
            str(snapshot.get("phase", "-"))[:16],
            str(snapshot.get("health", "-"))[:8],
            str(snapshot.get("cwd", "-"))[:8],
            str(snapshot.get("msg", 0)),
            str(snapshot.get("tool", 0)),
            str(snapshot.get("child", 0)),
            str(snapshot.get("todo", "-"))[:8],
            str(snapshot.get("quiet", 0)),
            str(snapshot.get("elapsed_ms", 0)),
            str(snapshot.get("note", ""))[:24],
        )
    return table


def render_once(states: list[LiveState], console: Console) -> None:
    console.print(render_state_table(states))


def sessions_idle(status: dict[str, Any], session_ids: list[str]) -> bool:
    for session_id in session_ids:
        value = status.get(session_id, {"type": "idle"})
        if isinstance(value, dict) and value.get("type") != "idle":
            return False
    return True


def idle_complete(status: dict[str, Any], session_ids: list[str], last_activity: float, quiet_seconds: float, now: float | None = None) -> bool:
    current = time.monotonic() if now is None else now
    return sessions_idle(status, session_ids) and current - last_activity >= quiet_seconds
