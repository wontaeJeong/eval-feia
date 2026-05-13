# pyright: reportMissingImports=false
from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.table import Table

from .models import json_safe


@dataclass
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
    worktree_path: str = ""
    started_monotonic: float = field(default_factory=time.monotonic)

    def update_elapsed(self) -> None:
        self.elapsed_seconds = time.monotonic() - self.started_monotonic


class ProgressEmitter:
    def __init__(self, *, json_output: bool, no_live: bool, display: "RichLiveDisplay | None" = None):
        self.json_output = json_output
        self.no_live = no_live
        self.display = display
        self._lock = threading.Lock()

    def emit(self, event: dict[str, Any]) -> None:
        with self._lock:
            if self.json_output:
                sys.stdout.write(json.dumps(json_safe(event), ensure_ascii=False) + "\n")
                sys.stdout.flush()
            elif self.no_live or self.display is None:
                sys.stdout.write(self._human_line(event) + "\n")
                sys.stdout.flush()
            else:
                self.display.print(self._human_line(event))

    def state(self, state: LiveState) -> None:
        if self.display is not None and not self.json_output and not self.no_live:
            self.display.update_state(state)

    @staticmethod
    def _human_line(event: dict[str, Any]) -> str:
        event_type = str(event.get("type", "event"))
        run_id = str(event.get("run_id", "-"))
        if event_type == "worktree_created":
            return f"[{run_id}] worktree: {event.get('path')}"
        if event_type == "server_info":
            return f"[{run_id}] server: {event.get('base_url')} version={event.get('version_check')} cwd={event.get('cwd_check')} restarts={event.get('restart_count')}"
        if event_type == "server_mismatch":
            return f"[{run_id}] mismatch: {event.get('reason')} expected={event.get('expected')} actual={event.get('actual')}"
        if event_type == "server_restart":
            return f"[{run_id}] restart: {event.get('action')} count={event.get('restart_count')}"
        if event_type in {"run_completed", "run_failed"}:
            return f"[{run_id}] {event_type}: {event.get('status', event.get('failure_class', ''))}"
        return f"[{run_id}] {event_type}"


class RichLiveDisplay:
    def __init__(self, *, enabled: bool = True):
        self.enabled = enabled
        self.console = Console(stderr=True)
        self.states: dict[str, LiveState] = {}
        self.refresh_count = 0
        self._live: Live | None = None
        self._lock = threading.Lock()

    def __enter__(self) -> "RichLiveDisplay":
        if self.enabled:
            live = Live(self._build_table(), console=self.console, screen=False, refresh_per_second=4)
            self._live = live
            live.__enter__()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._live is not None:
            self._live.__exit__(exc_type, exc, tb)

    def print(self, message: str) -> None:
        if self._live is not None:
            self._live.console.print(message)
        else:
            self.console.print(message)

    def update_state(self, state: LiveState) -> None:
        with self._lock:
            state.update_elapsed()
            self.states[state.run_id] = state
            self.refresh_count += 1
            if self._live is not None:
                self._live.update(self._build_table())

    def _build_table(self) -> Table:
        table = Table(title="eval-feia", expand=True)
        for column in ("Run", "Port", "Phase", "Health", "CWD", "Msg", "Tool", "Child", "Todo", "Quiet", "Elapsed", "Note"):
            table.add_column(column, no_wrap=True, overflow="ellipsis")
        for state in sorted(self.states.values(), key=lambda item: item.run_id):
            table.add_row(
                state.run_id,
                str(state.port),
                state.phase[:18],
                state.health[:8],
                state.cwd[:8],
                str(state.message_count),
                str(state.tool_call_count),
                str(state.child_session_count),
                state.todo_status[:10],
                f"{state.quiet_seconds:.0f}s",
                f"{state.elapsed_seconds:.0f}s",
                state.note[:24],
            )
        return table


def update_state_from_sse(state: LiveState, event_type: str) -> None:
    lowered = event_type.lower()
    if "message" in lowered:
        state.message_count += 1
    if "tool" in lowered and ("started" in lowered or "call" in lowered):
        state.tool_call_count += 1


def todo_status(items: list[dict[str, Any]]) -> str:
    if not items:
        return "none"
    active = sum(1 for item in items if str(item.get("status", "")).lower() in {"in_progress", "running", "pending"})
    done = sum(1 for item in items if str(item.get("status", "")).lower() in {"completed", "done"})
    return f"{done}/{len(items)}" if active == 0 else f"active {active}"
