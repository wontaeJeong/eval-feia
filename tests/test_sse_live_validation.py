# pyright: reportMissingImports=false
from __future__ import annotations

import io
import json
import time
from pathlib import Path

from rich.console import Console

from eval_feia.live import JsonlWriter, LiveState, idle_complete, render_once
from eval_feia.sse import SseParser
from eval_feia.validation import validate_worktree

from .conftest import valid_team_config


def test_sse_parser_basic_event() -> None:
    parser = SseParser()
    events = parser.feed_lines(['event: custom', 'data: {"type":"message.updated"}', ''])
    assert len(events) == 1
    assert events[0].event == "custom"
    assert events[0].json_data()["type"] == "message.updated"


def test_sse_parser_multiline_and_parse_error_count() -> None:
    parser = SseParser()
    events = parser.feed_lines(['data: {"a":', 'data: 1}', ''])
    assert events[0].data == '{"a":\n1}'
    assert events[0].json_data() == {"a": 1}
    parser.feed_lines(["data: {bad", ""])
    assert parser.parse_errors == 1


def test_live_state_message_tool_updates_and_render() -> None:
    state = LiveState("run-001", 4096)
    state.update_event({"json": {"type": "message.updated"}})
    state.update_event({"json": {"type": "tool.finished"}})
    state.update_children([{"id": "child"}])
    state.update_todo([{"status": "completed"}, {"status": "pending"}])
    assert state.message_count == 1
    assert state.tool_call_count == 1
    assert state.child_session_count == 1
    assert state.todo_status == "1/2"
    console = Console(record=True, width=120)
    render_once([state], console)
    assert "run-001" in console.export_text()


def test_jsonl_writer_flushes_each_line() -> None:
    class Tracking(io.StringIO):
        flushed = False

        def flush(self) -> None:
            self.flushed = True
            super().flush()

    stream = Tracking()
    JsonlWriter(stream).write({"type": "worktree_created", "path": "/tmp/x"})
    assert stream.flushed is True
    assert stream.getvalue().endswith("\n")
    assert json.loads(stream.getvalue())["type"] == "worktree_created"


def test_idle_detection_waits_for_child_sessions() -> None:
    now = time.monotonic()
    assert not idle_complete({"parent": {"type": "idle"}, "child": {"type": "busy"}}, ["parent", "child"], now - 10, 1, now)
    assert idle_complete({"parent": {"type": "idle"}, "child": {"type": "idle"}}, ["parent", "child"], now - 10, 1, now)


def test_validation_success_and_secret_failure(tmp_path: Path) -> None:
    (tmp_path / "team.json").write_text(json.dumps(valid_team_config()), encoding="utf-8")
    result = validate_worktree(tmp_path)
    assert result.validation_passed is True
    (tmp_path / "team.json").write_text('{"password":"sk-secret-secret-secret","agents":[],"model":"x","termination_condition":{}}', encoding="utf-8")
    result = validate_worktree(tmp_path)
    assert result.secret_scan_ok is False
    assert result.validation_passed is False
