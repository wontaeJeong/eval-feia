# pyright: reportMissingImports=false
from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import Any, cast

from eval_feia.models import FailureClass, RunConfig, RunRecord, RunStatus, ServerHealth
from eval_feia.orchestrator import BatchRunner
from eval_feia.process import HOSTNAME, ProcessHandle, TerminationResult

from .fake_opencode_server import FakeOpenCodeServer, FakeOpenCodeState, write_valid_team


def latest_batch(output_dir: Path) -> Path:
    return sorted(output_dir.glob("batch-*"))[-1]


class ArtifactBatchRunner(BatchRunner):
    def _poll_until_idle(self, client, session_id, record, paths, state) -> None:
        super()._poll_until_idle(client, session_id, record, paths, state)
        assert record.worktree is not None
        write_valid_team(Path(record.worktree.path))


def test_happy_path_sse_before_prompt_and_live_output(git_repo: Path, tmp_path: Path) -> None:
    expected_worktree = tmp_path / "tmp" / "unknown"
    state = FakeOpenCodeState(["1.4.6"], [str(expected_worktree)], str(expected_worktree))
    with FakeOpenCodeServer(state) as server:
        config = RunConfig(
            repo=git_repo,
            count=1,
            worktree_root=tmp_path / "tmp",
            output_dir=tmp_path / "results",
            fake_server_url=server.base_url,
            idle_quiet_seconds=0.2,
            health_poll_interval_seconds=0.01,
            json=True,
        )
        # The fake CWD must match the actual worktree path, which is deterministic for this batch/run shape
        # after BatchRunner creates the batch id. Use /project/current fallback by making /path match updated later.
        # Here we disable cwd check for the pure happy-path live ordering assertion.
        config.cwd_check = False
        record = ArtifactBatchRunner(config, io.StringIO()).run()[0]

    assert record.status == RunStatus.COMPLETED
    assert state.sse_connected_at is not None
    assert state.prompt_at is not None
    assert state.sse_connected_at <= state.prompt_at
    assert state.prompt_count == 1
    batch = latest_batch(tmp_path / "results")
    run_json = json.loads((batch / "runs" / "run-001" / "run.json").read_text())
    assert run_json["server_info"]["version_check"] == "match"
    assert run_json["live_summary"]["sse_connected_at"] is not None
    assert (batch / "runs" / "run-001" / "messages.json").exists()
    assert (batch / "runs" / "run-001" / "artifacts" / "team.json").exists()
    assert run_json["validation"]["artifact_path"].endswith("artifacts/team.json")
    lines = [json.loads(line) for line in (batch / "runs" / "run-001" / "events.jsonl").read_text().splitlines()]
    assert {line["type"] for line in lines} >= {"server.connected", "message.updated", "tool.call.started", "tool.call.completed"}


def test_health_timeout_blocks_prompt(git_repo: Path, tmp_path: Path) -> None:
    state = FakeOpenCodeState(["1.4.6"], [str(tmp_path)], str(tmp_path), health_delay=0.2)
    with FakeOpenCodeServer(state) as server:
        config = RunConfig(
            repo=git_repo,
            count=1,
            worktree_root=tmp_path / "tmp",
            output_dir=tmp_path / "results",
            fake_server_url=server.base_url,
            server_start_timeout_seconds=0.05,
            health_poll_interval_seconds=0.01,
            json=True,
            cwd_check=False,
        )
        record = BatchRunner(config, io.StringIO()).run()[0]
    assert record.failure_class == FailureClass.SERVER_UNHEALTHY
    assert state.prompt_count == 0


def test_version_mismatch_restarts_before_prompt(git_repo: Path, tmp_path: Path) -> None:
    state = FakeOpenCodeState(["1.4.5", "1.4.6"], [str(tmp_path), str(tmp_path)], str(tmp_path))
    with FakeOpenCodeServer(state) as server:
        config = RunConfig(
            repo=git_repo,
            count=1,
            worktree_root=tmp_path / "tmp",
            output_dir=tmp_path / "results",
            fake_server_url=server.base_url,
            idle_quiet_seconds=0.1,
            health_poll_interval_seconds=0.01,
            json=True,
            cwd_check=False,
        )
        record = BatchRunner(config, io.StringIO()).run()[0]
    assert len(record.server_restart_history) == 1
    assert record.server_restart_history[0].reason == "version_mismatch"
    assert state.prompt_count == 1
    assert state.prompts_by_attempt[0] == 0
    assert state.prompts_by_attempt[1] == 1


def test_cwd_mismatch_restarts_before_prompt(git_repo: Path, tmp_path: Path) -> None:
    wrong = tmp_path / "wrong"
    state = FakeOpenCodeState(["1.4.6", "1.4.6"], [str(wrong), ""], "")
    with FakeOpenCodeServer(state) as server:
        config = RunConfig(
            repo=git_repo,
            count=1,
            worktree_root=tmp_path / "tmp",
            output_dir=tmp_path / "results",
            fake_server_url=server.base_url,
            idle_quiet_seconds=0.1,
            health_poll_interval_seconds=0.01,
            json=True,
        )
        # Patch the fake state once the deterministic path is known by deriving it from the emitted manifest after first run attempt.
        # The second /path response intentionally returns an empty path so /project/current fallback is used.
        original_create = BatchRunner._emit_server_info

        def update_expected(self, info):
            if state.expected_cwd == "":
                state.expected_cwd = info.expected_cwd
            original_create(self, info)

        BatchRunner._emit_server_info = update_expected
        try:
            record = BatchRunner(config, io.StringIO()).run()[0]
        finally:
            BatchRunner._emit_server_info = original_create
    assert len(record.server_restart_history) == 1
    assert record.server_restart_history[0].reason == "cwd_mismatch"
    assert state.prompt_count == 1
    assert state.prompts_by_attempt[0] == 0
    assert state.prompts_by_attempt[1] == 1


def test_cwd_unknown_blocks_prompt(git_repo: Path, tmp_path: Path) -> None:
    state = FakeOpenCodeState(["1.4.6"], [""], "")
    with FakeOpenCodeServer(state) as server:
        config = RunConfig(
            repo=git_repo,
            count=1,
            worktree_root=tmp_path / "tmp",
            output_dir=tmp_path / "results",
            fake_server_url=server.base_url,
            health_poll_interval_seconds=0.01,
            max_server_restarts=0,
            json=True,
        )
        record = BatchRunner(config, io.StringIO()).run()[0]
    assert record.failure_class == FailureClass.SERVER_RESTART_EXHAUSTED
    assert state.prompt_count == 0


def test_sse_failure_blocks_prompt(git_repo: Path, tmp_path: Path) -> None:
    state = FakeOpenCodeState(["1.4.6"], [str(tmp_path)], str(tmp_path), sse_status=500)
    with FakeOpenCodeServer(state) as server:
        config = RunConfig(
            repo=git_repo,
            count=1,
            worktree_root=tmp_path / "tmp",
            output_dir=tmp_path / "results",
            fake_server_url=server.base_url,
            health_poll_interval_seconds=0.01,
            cwd_check=False,
            json=True,
        )
        record = BatchRunner(config, io.StringIO()).run()[0]
    assert record.failure_class == FailureClass.HARNESS_ERROR
    assert state.prompt_count == 0


def test_sse_closes_after_headers_blocks_prompt(git_repo: Path, tmp_path: Path) -> None:
    state = FakeOpenCodeState(["1.4.6"], [str(tmp_path)], str(tmp_path), sse_close_after_headers=True)
    with FakeOpenCodeServer(state) as server:
        config = RunConfig(
            repo=git_repo,
            count=1,
            worktree_root=tmp_path / "tmp",
            output_dir=tmp_path / "results",
            fake_server_url=server.base_url,
            health_poll_interval_seconds=0.01,
            cwd_check=False,
            json=True,
        )
        record = BatchRunner(config, io.StringIO()).run()[0]
    assert record.failure_class == FailureClass.HARNESS_ERROR
    assert state.prompt_count == 0


class FakeProcess:
    pid = 12345

    def poll(self) -> int | None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0


class FakeProcessManager:
    def __init__(self) -> None:
        self.stop_count = 0

    def start(self, cwd: Path, run_home: Path, run_tmp: Path, port: int, log_path: Path | None = None) -> ProcessHandle:
        return ProcessHandle(FakeProcess(), port, HOSTNAME, f"http://127.0.0.1:{port}", "pw", [])

    def stop(self, handle: ProcessHandle, grace_seconds: float = 5.0) -> TerminationResult:
        self.stop_count += 1
        return TerminationResult(True, False, 0)


class FakeClient:
    def __init__(self, base_url: str, password: str) -> None:
        self.prompt_count = 0

    def close(self) -> None:
        pass

    def poll_health(self, timeout_seconds: float, interval_seconds: float) -> ServerHealth:
        return ServerHealth(True, "1.4.6")

    def create_session(self, title: str) -> str:
        return "session-1"

    def stream_sse(self, endpoint: str = "/event", on_connected=None):
        if on_connected:
            on_connected()
        yield type("Event", (), {"event": "server.connected", "data": {"type": "server.connected"}})()
        time.sleep(0.2)

    def send_prompt_async(self, session_id: str, prompt: str, provider: str, model: str, agent: str) -> None:
        self.prompt_count += 1

    def session_status(self):
        return {"status": "idle"}

    def children(self, session_id: str):
        return {"children": []}

    def todo(self, session_id: str):
        return {"items": []}

    def diff(self, session_id: str) -> str:
        return ""

    def messages(self, session_id: str):
        return []


def test_process_stopped_on_success(git_repo: Path, tmp_path: Path) -> None:
    manager = FakeProcessManager()
    config = RunConfig(
        repo=git_repo,
        count=1,
        worktree_root=tmp_path / "tmp",
        output_dir=tmp_path / "results",
        idle_quiet_seconds=0.01,
        health_poll_interval_seconds=0.01,
        cwd_check=False,
        json=True,
    )
    record = ArtifactBatchRunner(
        config,
        io.StringIO(),
        process_manager=cast(Any, manager),
        client_factory=cast(Any, FakeClient),
    ).run()[0]
    assert record.status == RunStatus.COMPLETED
    assert manager.stop_count == 1


class SlowRunner(BatchRunner):
    def _run_index(self, index: int, batch_dir: Path, manager) -> RunRecord:
        time.sleep(0.1)
        return RunRecord(run_id=f"run-{index:03d}", batch_id=batch_dir.name, status=RunStatus.COMPLETED)


def test_concurrency_runs_indices_in_parallel(git_repo: Path, tmp_path: Path) -> None:
    config = RunConfig(repo=git_repo, count=2, concurrency=2, worktree_root=tmp_path / "tmp", output_dir=tmp_path / "results")
    started = time.monotonic()
    SlowRunner(config, io.StringIO()).run()
    assert time.monotonic() - started < 0.18
