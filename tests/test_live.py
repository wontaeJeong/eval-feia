from __future__ import annotations

import io

from eval_feia.live import JsonlWriter, LiveRunState, build_table, is_idle


def test_live_state_updates_messages_tools_children_and_todo() -> None:
    state = LiveRunState("run-001")
    state.apply_event({"type": "message.updated"})
    state.apply_event({"type": "tool.executed"})
    state.update_children([{"id": "child", "status": "idle"}])
    state.update_todo([{"status": "completed"}, {"status": "pending"}])
    assert state.message_count == 1
    assert state.tool_call_count == 1
    assert state.child_session_count == 1
    assert state.todo_status == "1/2"


def test_jsonl_writer_flushes_each_line() -> None:
    stream = io.StringIO()
    writer = JsonlWriter(stream=stream)
    writer.write({"type": "run_progress", "run_id": "run-001"})
    assert stream.getvalue().endswith("\n")
    assert '"type":"run_progress"' in stream.getvalue()


def test_idle_detection_waits_for_children() -> None:
    assert not is_idle({"status": "idle"}, [{"status": "running"}], 10, 1)
    assert is_idle({"status": "idle"}, [], 10, 1)


def test_rich_table_builds_short_columns() -> None:
    table = build_table([LiveRunState("run-001", port=4096, phase="running")])
    assert table.row_count == 1
