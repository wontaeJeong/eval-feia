# pyright: reportMissingImports=false
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import httpx


@dataclass(slots=True)
class SseEvent:
    event: str
    data: str
    id: str | None = None

    def json_data(self) -> Any | None:
        if not self.data:
            return None
        return json.loads(self.data)

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {"event": self.event, "data": self.data}
        if self.id is not None:
            record["id"] = self.id
        try:
            record["json"] = self.json_data()
        except json.JSONDecodeError:
            record["json_error"] = True
        return record


class SseParser:
    def __init__(self) -> None:
        self._event = "message"
        self._data: list[str] = []
        self._id: str | None = None
        self.parse_errors = 0

    def feed_line(self, line: str) -> list[SseEvent]:
        if line == "":
            if not self._data:
                self._event = "message"
                self._id = None
                return []
            event = SseEvent(event=self._event, data="\n".join(self._data), id=self._id)
            self._event = "message"
            self._data = []
            self._id = None
            try:
                event.json_data()
            except json.JSONDecodeError:
                self.parse_errors += 1
            return [event]
        if line.startswith(":"):
            return []
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            self._event = value or "message"
        elif field == "data":
            self._data.append(value)
        elif field == "id":
            self._id = value
        return []

    def feed_lines(self, lines: Iterable[str]) -> list[SseEvent]:
        events: list[SseEvent] = []
        for line in lines:
            events.extend(self.feed_line(line.rstrip("\r\n")))
        return events


class SseListener:
    def __init__(
        self,
        base_url: str,
        endpoint: str,
        username: str,
        password: str,
        directory: str | None,
        on_event: Callable[[SseEvent], None],
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoint = endpoint
        self.username = username
        self.password = password
        self.directory = directory
        self.on_event = on_event
        self.timeout = timeout
        self.connected = threading.Event()
        self.stopped = threading.Event()
        self.thread: threading.Thread | None = None
        self.parser = SseParser()
        self.error: str | None = None
        self._client: httpx.Client | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="eval-feia-sse", daemon=True)
        self.thread.start()

    def wait_connected(self, timeout: float) -> bool:
        return self.connected.wait(timeout)

    def stop(self) -> None:
        self.stopped.set()
        if self._client is not None:
            self._client.close()
        if self.thread is not None:
            self.thread.join(timeout=2.0)

    def _run(self) -> None:
        params = {"directory": self.directory} if self.directory else None
        try:
            with httpx.Client(
                base_url=self.base_url,
                auth=(self.username, self.password),
                timeout=httpx.Timeout(self.timeout, read=None),
                headers={"Accept": "text/event-stream"},
            ) as client:
                self._client = client
                with client.stream("GET", self.endpoint, params=params) as response:
                    response.raise_for_status()
                    self.connected.set()
                    for line in response.iter_lines():
                        if self.stopped.is_set():
                            break
                        for event in self.parser.feed_line(line):
                            self.on_event(event)
        except Exception as exc:  # pragma: no cover - exact network errors vary
            self.error = str(exc)
            self.connected.set()
        finally:
            self.stopped.set()
