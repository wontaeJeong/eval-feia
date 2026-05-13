# pyright: reportMissingImports=false
from __future__ import annotations

import json
from pathlib import Path

from eval_feia.models import RunOptions
from eval_feia.orchestrator import BatchRunner
from eval_feia.process import TerminationResult

from .conftest import FakeOpenCodeServer, FakeOpenCodeState


class FakeProcess:
    def __init__(self, *, base_url: str, port: int, state: FakeOpenCodeState):
        self.base_url = base_url
        self.port = port
        self.hostname = "127.0.0.1"
        self.username = "opencode"
        self.password = None
        self.pid = 1000 + state.current_attempt
        self.state = state
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    def stop(self, grace_seconds: float = 5.0) -> TerminationResult:
        self.alive = False
        self.state.stop_attempt()
        return TerminationResult(True, False, 0)


class SequencedProcessManager:
    def __init__(self, server: FakeOpenCodeServer, state: FakeOpenCodeState):
        self.server = server
        self.state = state

    def start(self, *, cwd: Path, run_home: Path, run_tmp: Path, port: int, version: str, log_path: Path, hostname: str):
        self.state.start_attempt(cwd)
        return FakeProcess(base_url=self.server.url, port=port, state=self.state)


def _options(tmp_path: Path, git_repo: Path) -> RunOptions:
    return RunOptions(
        repo=git_repo,
        count=1,
        concurrency=1,
        output_dir=tmp_path / "results",
        worktree_root=tmp_path / "worktrees",
        idle_quiet_seconds=0.05,
        hard_timeout_seconds=5,
        server_start_timeout_seconds=2,
        health_poll_interval_seconds=0.05,
        no_live=True,
    )


def test_fake_server_happy_path_orders_sse_before_prompt(tmp_path: Path, git_repo: Path) -> None:
    state = FakeOpenCodeState()
    server = FakeOpenCodeServer(state).start()
    try:
        runner = BatchRunner(_options(tmp_path, git_repo), process_manager=SequencedProcessManager(server, state))
        result = runner.run()
    finally:
        server.stop()
    assert result.failed_count == 0
    assert state.prompts == [1]
    assert state.prompt_before_sse == []
    record = result.records[0]
    assert record.server_info is not None
    assert record.server_info.cwd_check == "ok"
    assert record.live_summary.total_sse_events >= 4
    run_json = json.loads((result.batch_dir / "runs" / "run-001" / "run.json").read_text(encoding="utf-8"))
    assert run_json["server_info"]["version_check"] == "match"
    assert run_json["validation"]["validation_passed"] is True
    progress_lines = (result.batch_dir / "manifest.json").read_text(encoding="utf-8")
    assert "worktree" in progress_lines


def test_version_mismatch_restarts_before_prompt(tmp_path: Path, git_repo: Path) -> None:
    state = FakeOpenCodeState(version_sequence=["1.4.5", "1.4.6"])
    server = FakeOpenCodeServer(state).start()
    try:
        runner = BatchRunner(_options(tmp_path, git_repo), process_manager=SequencedProcessManager(server, state))
        result = runner.run()
    finally:
        server.stop()
    assert result.failed_count == 0
    assert state.starts == 2
    assert state.prompts == [2]
    assert result.records[0].server_info is not None
    assert result.records[0].server_info.restart_count == 1


def test_cwd_mismatch_restarts_before_prompt(tmp_path: Path, git_repo: Path) -> None:
    wrong = str(tmp_path / "wrong-cwd")
    state = FakeOpenCodeState(cwd_sequence=[wrong, None])
    server = FakeOpenCodeServer(state).start()
    try:
        runner = BatchRunner(_options(tmp_path, git_repo), process_manager=SequencedProcessManager(server, state))
        result = runner.run()
    finally:
        server.stop()
    assert result.failed_count == 0
    assert state.starts == 2
    assert state.prompts == [2]
    assert result.records[0].server_restart_history[0]["reason"] == "cwd_mismatch"


def test_restart_exhaustion_fails_without_prompt(tmp_path: Path, git_repo: Path) -> None:
    options = _options(tmp_path, git_repo)
    options.max_server_restarts = 0
    state = FakeOpenCodeState(version_sequence=["0.0.0"])
    server = FakeOpenCodeServer(state).start()
    try:
        runner = BatchRunner(options, process_manager=SequencedProcessManager(server, state))
        result = runner.run()
    finally:
        server.stop()
    assert result.failed_count == 1
    assert state.prompts == []
    assert result.records[0].failure_class == "server_restart_exhausted"
