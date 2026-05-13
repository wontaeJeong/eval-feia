from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(slots=True)
class SseEvent:
    event: str
    data: str
    id: str | None = None
    retry: int | None = None
    parsed: Any = None
    parse_error: str | None = None


@dataclass(slots=True)
class SseParser:
    event_name: str = "message"
    data_lines: list[str] = field(default_factory=list)
    event_id: str | None = None
    retry: int | None = None
    parse_error_count: int = 0

    def feed_line(self, line: str) -> list[SseEvent]:
        if line.endswith("\r"):
            line = line[:-1]
        if line == "":
            event = self._flush()
            return [event] if event else []
        if line.startswith(":"):
            return []
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            self.event_name = value or "message"
        elif field == "data":
            self.data_lines.append(value)
        elif field == "id":
            self.event_id = value
        elif field == "retry":
            try:
                self.retry = int(value)
            except ValueError:
                self.parse_error_count += 1
        return []

    def finish(self) -> list[SseEvent]:
        event = self._flush()
        return [event] if event else []

    def _flush(self) -> SseEvent | None:
        if not self.data_lines:
            self.event_name = "message"
            self.event_id = None
            self.retry = None
            return None
        data = "\n".join(self.data_lines)
        parsed: Any = None
        parse_error: str | None = None
        stripped = data.strip()
        if stripped:
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                parse_error = str(exc)
                self.parse_error_count += 1
        event = SseEvent(
            event=self.event_name or "message",
            data=data,
            id=self.event_id,
            retry=self.retry,
            parsed=parsed,
            parse_error=parse_error,
        )
        self.event_name = "message"
        self.data_lines = []
        self.event_id = None
        self.retry = None
        return event


def parse_sse_lines(lines: Iterable[str]) -> tuple[list[SseEvent], int]:
    parser = SseParser()
    events: list[SseEvent] = []
    for line in lines:
        events.extend(parser.feed_line(line))
    events.extend(parser.finish())
    return events, parser.parse_error_count
