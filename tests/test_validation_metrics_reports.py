# pyright: reportMissingImports=false
from __future__ import annotations

import csv
import copy
import json
from pathlib import Path

from eval_feia.metrics import metrics_from_events
from eval_feia.models import RunRecord
from eval_feia.reports import SUMMARY_COLUMNS, run_summary_row, write_summary
from eval_feia.validation import validate_artifacts

from .fake_opencode_server import VALID_TEAM


def test_validation_success_and_validation_json(tmp_path: Path) -> None:
    (tmp_path / "team.json").write_text(json.dumps(VALID_TEAM))
    result = validate_artifacts(tmp_path, tmp_path / "validation.json")
    assert result.validation_passed
    payload = json.loads((tmp_path / "validation.json").read_text())
    assert payload["artifact_found"] is True
    assert payload["autogen_load_ok"] is None


def test_validation_rejects_secret(tmp_path: Path) -> None:
    bad = copy.deepcopy(VALID_TEAM)
    bad["config"]["api_key"] = "sk-realisticlongsecretvalue1234567890"
    (tmp_path / "team.json").write_text(json.dumps(bad))
    result = validate_artifacts(tmp_path)
    assert not result.validation_passed
    assert not result.secret_scan_ok


def test_metrics_from_events(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(
        '\n'.join(
            [
                json.dumps({"type": "message.updated", "role": "user"}),
                json.dumps({"type": "message.updated", "role": "assistant"}),
                json.dumps({"type": "tool.call.completed"}),
                json.dumps({"type": "server_restart"}),
            ]
        )
        + "\n"
    )
    metrics = metrics_from_events(events)
    assert metrics.total_messages == 2
    assert metrics.user_message_count == 1
    assert metrics.assistant_message_count == 1
    assert metrics.total_tool_calls == 1
    assert metrics.server_restart_count == 1


def test_summary_csv_schema(tmp_path: Path) -> None:
    record = RunRecord(run_id="run-001", batch_id="batch-1")
    row = run_summary_row(record, "openai", "gpt-5.5", "1.4.6")
    write_summary(tmp_path, [row])
    with (tmp_path / "summary.csv").open() as file:
        reader = csv.DictReader(file)
        assert reader.fieldnames == SUMMARY_COLUMNS
        rows = list(reader)
    assert rows[0]["run_id"] == "run-001"
    assert json.loads((tmp_path / "summary.json").read_text())["runs"][0]["run_id"] == "run-001"
