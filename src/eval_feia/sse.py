from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator

from .models import LiveSummary, now_iso
from .reports import JsonlWriter


@dataclass
class SSEEvent:
    event: str | None
    data: str
    json_data: Any = None
    parse_error: str | None = None

    @property
    def type(self) -> str:
        if self.event:
            return self.event
        if isinstance(self.json_data, dict) and isinstance(self.json_data.get("type"), str):
            return self.json_data["type"]
        return "message"

    def to_record(self, run_id: str) -> dict[str, Any]:
        record: dict[str, Any] = {"type": "sse_event", "run_id": run_id, "event": self.type, "data": self.data}
        if self.json_data is not None:
            record["json"] = self.json_data
        if self.parse_error:
            record["parse_error"] = self.parse_error
        return record


def parse_sse_lines(lines: Iterable[str]) -> Iterator[SSEEvent]:
    event_name: str | None = None
    data_lines: list[str] = []
    for raw_line in lines:
        line = raw_line.rstrip("\r")
        if line == "":
            if data_lines or event_name:
                data = "\n".join(data_lines)
                yield _build_event(event_name, data)
            event_name = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if ":" in line:
            field, value = line.split(":", 1)
            if value.startswith(" "):
                value = value[1:]
        else:
            field, value = line, ""
        if field == "event":
            event_name = value
        elif field == "data":
            data_lines.append(value)
    if data_lines or event_name:
        yield _build_event(event_name, "\n".join(data_lines))


def _build_event(event_name: str | None, data: str) -> SSEEvent:
    if data == "":
        return SSEEvent(event_name, data)
    try:
        parsed = json.loads(data)
        return SSEEvent(event_name, data, parsed)
    except json.JSONDecodeError as exc:
        return SSEEvent(event_name, data, None, str(exc))


class SSEListener:
    def __init__(
        self,
        *,
        run_id: str,
        client: Any,
        endpoint: str,
        events_writer: JsonlWriter,
        live_summary: LiveSummary,
        on_event: Callable[[SSEEvent], None] | None = None,
    ):
        self.run_id = run_id
        self.client = client
        self.endpoint = endpoint
        self.events_writer = events_writer
        self.live_summary = live_summary
        self.on_event = on_event
        self.connected = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"sse-{run_id}", daemon=True)
        self.last_event_monotonic: float | None = None
        self.error: str | None = None

    def start(self) -> None:
        self.live_summary.sse_endpoint = self.endpoint
        self.live_summary.sse_listener_started_at = now_iso()
        self._thread.start()

    def wait_connected(self, timeout: float) -> bool:
        return self.connected.wait(timeout)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        try:
            with self.client.open_event_lines(self.endpoint) as lines:
                self.live_summary.sse_connected_at = now_iso()
                self.connected.set()
                for event in parse_sse_lines(lines):
                    if self._stop.is_set():
                        break
                    current_iso = now_iso()
                    if self.live_summary.first_event_at is None:
                        self.live_summary.first_event_at = current_iso
                    self.live_summary.last_event_at = current_iso
                    self.live_summary.total_sse_events += 1
                    if event.parse_error:
                        self.live_summary.sse_parser_errors += 1
                    self.last_event_monotonic = time.monotonic()
                    self.events_writer.write(event.to_record(self.run_id))
                    if self.on_event:
                        self.on_event(event)
        except Exception as exc:
            self.error = str(exc)
            self.events_writer.write({"type": "sse_error", "run_id": self.run_id, "error": self.error})
            self.connected.set()
