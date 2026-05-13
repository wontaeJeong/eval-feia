from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from eval_feia.live import JsonProgressSink, JsonlWriter
from eval_feia.models import BatchSpec, HealthCheck
from eval_feia.orchestrator import BatchRunner, can_submit_prompt

from .conftest import FakeOpenCodeServer


class FakeServerProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.password = "pw"
        self.alive = True
        self.returncode: int | None = None

    def is_alive(self) -> bool:
        return self.alive


class FakeProcessManager:
    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0
        self.processes: list[FakeServerProcess] = []

    def start(self, **_kwargs: Any) -> FakeServerProcess:
        self.starts += 1
        process = FakeServerProcess(1000 + self.starts)
        self.processes.append(process)
        return process

    def stop(self, server: FakeServerProcess, grace_seconds: float = 3.0) -> dict[str, object]:
        self.stops += 1
        server.alive = False
        server.returncode = -15
        return {"pid": server.pid, "terminated": True, "killed": False, "returncode": server.returncode}


class ExplodingCwdClient:
    def __init__(self, **_kwargs: Any) -> None:
        self.closed = False

    def poll_health(self, *_args: Any) -> HealthCheck:
        return HealthCheck(ok=True, healthy=True, version="1.4.6")

    def verify_cwd(self, _path: Path):
        raise RuntimeError("cwd probe exploded")

    def close(self) -> None:
        self.closed = True


def make_spec(git_repo: Path, tmp_path: Path, port: int, **kwargs: Any) -> BatchSpec:
    return BatchSpec(
        repo=git_repo,
        count=1,
        concurrency=1,
        output_dir=tmp_path / "results",
        worktree_root=tmp_path / "worktrees",
        base_port=port,
        opencode_version="1.4.6",
        server_start_timeout_seconds=1,
        health_poll_interval_seconds=0.01,
        idle_quiet_seconds=0,
        hard_timeout_seconds=5,
        json=True,
        batch_id="batch-test",
        **kwargs,
    )


def test_prompt_gating_blocks_mismatch() -> None:
    ok, missing = can_submit_prompt(
        worktree_created=True,
        server_process_alive=True,
        health_ok=True,
        server_info_emitted=True,
        version_check="match",
        cwd_check="mismatch",
        session_created=True,
        sse_connected=True,
    )
    assert ok is False
    assert "cwd_check" in missing


def test_prompt_gating_blocks_unknown_cwd() -> None:
    ok, missing = can_submit_prompt(
        worktree_created=True,
        server_process_alive=True,
        health_ok=True,
        server_info_emitted=True,
        version_check="match",
        cwd_check="unknown",
        session_created=True,
        sse_connected=True,
    )
    assert ok is False
    assert "cwd_check" in missing


def test_port_allocation_is_distinct(git_repo: Path, tmp_path: Path) -> None:
    spec = BatchSpec(repo=git_repo, count=3, concurrency=1, output_dir=tmp_path / "results", worktree_root=tmp_path / "worktrees", base_port=5000)
    run_specs = BatchRunner(spec, sink=JsonProgressSink(JsonlWriter(stream=io.StringIO())), process_manager=FakeProcessManager()).build_run_specs()
    assert [item.port for item in run_specs] == [5000, 5001, 5002]


def test_happy_path_outputs_worktree_server_info_and_artifacts(git_repo: Path, tmp_path: Path) -> None:
    server = FakeOpenCodeServer(str(tmp_path), echo_directory=True).start()
    stream = io.StringIO()
    process_manager = FakeProcessManager()
    try:
        records, batch_dir = BatchRunner(make_spec(git_repo, tmp_path, server.port), sink=JsonProgressSink(JsonlWriter(stream=stream)), process_manager=process_manager).run()
    finally:
        server.stop()
    assert records[0].status == "completed"
    assert server.prompt_after_sse is True
    assert process_manager.starts == 1
    output = stream.getvalue()
    assert '"type":"worktree_created"' in output
    assert '"type":"server_info"' in output
    run_json = json.loads((batch_dir / "runs" / "run-001" / "run.json").read_text(encoding="utf-8"))
    assert run_json["server_info"]["cwd_check"] == "ok"
    assert (batch_dir / "manifest.json").exists()
    assert (batch_dir / "summary.csv").exists()
    assert (batch_dir / "runs" / "run-001" / "validation.json").exists()


def test_restart_on_version_mismatch_does_not_prompt_first_attempt(git_repo: Path, tmp_path: Path) -> None:
    server = FakeOpenCodeServer(str(tmp_path), versions=["1.4.5", "1.4.6"], echo_directory=True).start()
    process_manager = FakeProcessManager()
    try:
        records, _batch_dir = BatchRunner(make_spec(git_repo, tmp_path, server.port), sink=JsonProgressSink(JsonlWriter(stream=io.StringIO())), process_manager=process_manager).run()
    finally:
        server.stop()
    assert records[0].status == "completed"
    assert process_manager.starts == 2
    assert process_manager.stops >= 2
    assert server.prompt_count == 1
    assert records[0].server_restart_history[0]["reason"] == "version_mismatch"


def test_restart_on_cwd_unknown_blocks_first_prompt(git_repo: Path, tmp_path: Path) -> None:
    server = FakeOpenCodeServer(str(tmp_path), path_returns_empty=True, project_returns_empty=True).start()
    process_manager = FakeProcessManager()
    try:
        records, _batch_dir = BatchRunner(make_spec(git_repo, tmp_path, server.port, max_server_restarts=0), sink=JsonProgressSink(JsonlWriter(stream=io.StringIO())), process_manager=process_manager).run()
    finally:
        server.stop()
    assert records[0].status == "failed"
    assert records[0].failure_class == "server_restart_exhausted"
    assert server.prompt_count == 0


def test_sse_events_after_prompt_are_logged_and_counted(git_repo: Path, tmp_path: Path) -> None:
    server = FakeOpenCodeServer(str(tmp_path), echo_directory=True, sse_after_prompt_events=[{"type": "message.updated", "role": "assistant"}, {"type": "tool.executed", "status": "success"}]).start()
    process_manager = FakeProcessManager()
    try:
        records, batch_dir = BatchRunner(make_spec(git_repo, tmp_path, server.port), sink=JsonProgressSink(JsonlWriter(stream=io.StringIO())), process_manager=process_manager).run()
    finally:
        server.stop()
    assert records[0].live_summary.total_sse_events >= 3
    assert records[0].metrics.total_messages >= 1
    assert records[0].metrics.total_tool_calls >= 1
    events_text = (batch_dir / "runs" / "run-001" / "events.jsonl").read_text(encoding="utf-8")
    assert "message.updated" in events_text


def test_readiness_exception_stops_started_server(git_repo: Path, tmp_path: Path) -> None:
    process_manager = FakeProcessManager()
    records, _batch_dir = BatchRunner(
        make_spec(git_repo, tmp_path, 4567),
        sink=JsonProgressSink(JsonlWriter(stream=io.StringIO())),
        process_manager=process_manager,
        client_factory=ExplodingCwdClient,
    ).run()
    assert records[0].status == "failed"
    assert process_manager.starts == 1
    assert process_manager.stops >= 1


def test_restart_exhaustion_blocks_prompt(git_repo: Path, tmp_path: Path) -> None:
    server = FakeOpenCodeServer(str(tmp_path), versions=["1.4.5"], echo_directory=True).start()
    process_manager = FakeProcessManager()
    try:
        records, _batch_dir = BatchRunner(make_spec(git_repo, tmp_path, server.port, max_server_restarts=0), sink=JsonProgressSink(JsonlWriter(stream=io.StringIO())), process_manager=process_manager).run()
    finally:
        server.stop()
    assert records[0].status == "failed"
    assert records[0].failure_class == "server_restart_exhausted"
    assert server.prompt_count == 0
