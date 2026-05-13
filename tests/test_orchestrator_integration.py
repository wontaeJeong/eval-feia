# pyright: reportMissingImports=false, reportArgumentType=false
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from eval_feia.models import BatchOptions, RunResult
from eval_feia.orchestrator import run_batch

from .conftest import FakeOpenCodeServer, FakeOpenCodeState, FakeProcessManager


def options(repo: Path, tmp_path: Path, server: FakeOpenCodeServer, **overrides: object) -> BatchOptions:
    values: dict[str, Any] = dict(
        repo=repo,
        count=1,
        concurrency=1,
        prompt="make a Knox mail report team",
        skill="build",
        worktree_root=tmp_path / "worktrees",
        output_dir=tmp_path / "results",
        base_port=server.port,
        opencode_version="1.4.6",
        server_start_timeout_seconds=1,
        health_poll_interval_seconds=0.02,
        idle_quiet_seconds=0.05,
        hard_timeout_seconds=2,
        json=True,
    )
    values.update(overrides)
    return BatchOptions(**values)


def run_with_server(git_repo: Path, tmp_path: Path, state: FakeOpenCodeState) -> tuple[FakeOpenCodeServer, Path, list[RunResult], str]:
    server = FakeOpenCodeServer(state).start()
    stream = io.StringIO()
    try:
        batch_dir, results = run_batch(options(git_repo, tmp_path, server), stream, lambda _message: None, process_manager=FakeProcessManager(server))
        return server, batch_dir, results, stream.getvalue()
    except Exception:
        server.stop()
        raise


def test_fake_server_happy_path_outputs_files_and_orders_sse_before_prompt(git_repo: Path, tmp_path: Path) -> None:
    server, batch_dir, results, output = run_with_server(git_repo, tmp_path, FakeOpenCodeState(child_ids=["child-1"]))
    try:
        assert results[0].status == "completed"
        assert server.state.prompt_count == 1
        assert server.state.prompt_before_sse is False
        assert server.state.order.index("sse") < server.state.order.index("prompt")
        assert (batch_dir / "manifest.json").exists()
        assert (batch_dir / "summary.json").exists()
        assert (batch_dir / "summary.csv").exists()
        run_dir = batch_dir / "runs" / "run-001"
        for name in ["run.json", "events.jsonl", "status_snapshots.jsonl", "children_snapshots.jsonl", "todo_snapshots.jsonl", "validation.json"]:
            assert (run_dir / name).exists()
        assert (run_dir / "artifacts" / "team.json").exists()
        manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["runs"][0]["worktree"]["path"]
        events = [json.loads(line) for line in output.splitlines()]
        assert any(event["type"] == "worktree_created" for event in events)
        assert any(event["type"] == "server_info" for event in events)
        run_data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        assert run_data["live_summary"]["sse_parser_errors"] == 0
    finally:
        server.stop()


def test_version_mismatch_restarts_before_prompt(git_repo: Path, tmp_path: Path) -> None:
    server, _batch_dir, results, _output = run_with_server(git_repo, tmp_path, FakeOpenCodeState(versions=["1.4.5", "1.4.6"]))
    try:
        assert results[0].status == "completed"
        assert server.state.start_count == 2
        assert server.state.stop_count >= 2
        assert server.state.prompt_count == 1
    finally:
        server.stop()


def test_cwd_mismatch_restarts_before_prompt(git_repo: Path, tmp_path: Path) -> None:
    server, _batch_dir, results, _output = run_with_server(git_repo, tmp_path, FakeOpenCodeState(cwd_modes=["wrong", "match"]))
    try:
        assert results[0].status == "completed"
        assert server.state.start_count == 2
        assert server.state.prompt_count == 1
    finally:
        server.stop()


def test_restart_exhaustion_fails_without_prompt(git_repo: Path, tmp_path: Path) -> None:
    server = FakeOpenCodeServer(FakeOpenCodeState(versions=["1.4.5", "1.4.5"])).start()
    stream = io.StringIO()
    try:
        batch_dir, results = run_batch(
            options(git_repo, tmp_path, server, max_server_restarts=0),
            stream,
            lambda _message: None,
            process_manager=FakeProcessManager(server),
        )
        assert results[0].status == "failed"
        assert results[0].failure_class == "server_restart_exhausted"
        assert server.state.prompt_count == 0
        assert (batch_dir / "runs" / "run-001" / "run.json").exists()
    finally:
        server.stop()


def test_health_timeout_fails_without_session_or_prompt(git_repo: Path, tmp_path: Path) -> None:
    server = FakeOpenCodeServer(FakeOpenCodeState(healthy=False)).start()
    stream = io.StringIO()
    try:
        _batch_dir, results = run_batch(
            options(git_repo, tmp_path, server, server_start_timeout_seconds=0.05),
            stream,
            lambda _message: None,
            process_manager=FakeProcessManager(server),
        )
        assert results[0].failure_class == "server_unhealthy"
        assert server.state.session_count == 0
        assert server.state.prompt_count == 0
    finally:
        server.stop()


def test_closed_sse_stream_blocks_prompt(git_repo: Path, tmp_path: Path) -> None:
    server = FakeOpenCodeServer(FakeOpenCodeState(sse_close_immediately=True)).start()
    stream = io.StringIO()
    try:
        batch_dir, results = run_batch(
            options(git_repo, tmp_path, server),
            stream,
            lambda _message: None,
            process_manager=FakeProcessManager(server),
        )
        assert results[0].failure_class == "harness_error"
        assert server.state.prompt_count == 0
        assert (batch_dir / "runs" / "run-001" / "diff.patch").exists()
    finally:
        server.stop()
