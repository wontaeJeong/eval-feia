from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Iterator


@dataclass(slots=True)
class SSEEvent:
    event: str | None
    data: Any
    raw: str


@dataclass(slots=True)
class SSEParseResult:
    events: list[SSEEvent]
    errors: int = 0


class SSEParser:
    def __init__(self) -> None:
        self.errors = 0
        self._event: str | None = None
        self._data_lines: list[str] = []

    def feed_line(self, line: str) -> SSEEvent | None:
        line = line.rstrip("\r\n")
        if line == "":
            return self._flush()
        if line.startswith(":"):
            return None
        if line.startswith("event:"):
            self._event = line.split(":", 1)[1].strip()
            return None
        if line.startswith("data:"):
            self._data_lines.append(line.split(":", 1)[1].lstrip())
            return None
        return None

    def finish(self) -> SSEEvent | None:
        return self._flush()

    def _flush(self) -> SSEEvent | None:
        if self._event is None and not self._data_lines:
            return None
        raw_data = "\n".join(self._data_lines)
        data: Any = raw_data
        if raw_data:
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                self.errors += 1
        event = SSEEvent(event=self._event, data=data, raw=raw_data)
        self._event = None
        self._data_lines = []
        return event


def parse_sse_lines(lines: Iterable[str]) -> SSEParseResult:
    parser = SSEParser()
    events: list[SSEEvent] = []
    for line in lines:
        event = parser.feed_line(line)
        if event is not None:
            events.append(event)
    trailing = parser.finish()
    if trailing is not None:
        events.append(trailing)
    return SSEParseResult(events=events, errors=parser.errors)


def iter_sse_events(lines: Iterable[str]) -> Iterator[SSEEvent]:
    parser = SSEParser()
    for line in lines:
        event = parser.feed_line(line)
        if event is not None:
            yield event
    event = parser.finish()
    if event is not None:
        yield event
