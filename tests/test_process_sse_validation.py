# pyright: reportMissingImports=false
from __future__ import annotations

import json
from pathlib import Path

from eval_feia.live import LiveState, todo_status, update_state_from_sse
from eval_feia.opencode_client import extract_cwd_value
from eval_feia.process import build_opencode_command
from eval_feia.sse import parse_sse_lines
from eval_feia.validation import validate_worktree


def test_command_builder_uses_version_pinned_bunx() -> None:
    command = build_opencode_command("1.4.6", 4999)
    assert command == [
        "bunx",
        "-p",
        "opencode-ai@1.4.6",
        "opencode",
        "serve",
        "--hostname",
        "127.0.0.1",
        "--port",
        "4999",
    ]


def test_cwd_extraction_supports_project_fallback_shape() -> None:
    assert extract_cwd_value({"cwd": "/tmp/a"}) == "/tmp/a"
    assert extract_cwd_value({"project": {"root": "/tmp/b"}}) == "/tmp/b"


def test_sse_parser_basic_multiline_and_parse_error() -> None:
    lines = [
        "event: message.updated",
        'data: {"type":"message.updated",',
        'data: "value": 1}',
        "",
        "event: bad",
        "data: {not-json}",
        "",
    ]
    events = list(parse_sse_lines(lines))
    assert events[0].event == "message.updated"
    assert events[0].json_data == {"type": "message.updated", "value": 1}
    assert events[1].parse_error is not None


def test_live_state_updates_and_todo_summary() -> None:
    state = LiveState(run_id="run-001", port=4096)
    update_state_from_sse(state, "message.updated")
    update_state_from_sse(state, "tool.call.started")
    assert state.message_count == 1
    assert state.tool_call_count == 1
    assert todo_status([{"status": "completed"}, {"status": "completed"}]) == "2/2"


def test_validation_success_and_secret_failure(tmp_path: Path) -> None:
    team = {
        "provider": "autogen",
        "component_type": "team",
        "participants": [
            {
                "name": "agent",
                "model_client": {"provider": "openai", "model": "gpt"},
                "tools": ["web_search", "mail_tool"],
                "system_message": "Search web, summarize Knox mail report findings.",
            }
        ],
        "termination_condition": {"type": "max_messages"},
    }
    (tmp_path / "team.json").write_text(json.dumps(team), encoding="utf-8")
    result = validate_worktree(tmp_path)
    assert result.validation_passed

    team["password"] = "hardcoded-secret-value"
    (tmp_path / "team.json").write_text(json.dumps(team), encoding="utf-8")
    failed = validate_worktree(tmp_path)
    assert not failed.secret_scan_ok
    assert not failed.validation_passed
