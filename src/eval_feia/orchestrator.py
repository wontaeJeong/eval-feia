from __future__ import annotations

import json
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from .live import LiveState, LiveStateStore, RichLiveRenderer
from .metrics import merge_validation_metrics, metrics_from_events
from .models import (
    BatchManifest,
    CwdCheckResult,
    CwdCheckStatus,
    FailureClass,
    LiveSummary,
    RestartHistoryEntry,
    RunConfig,
    RunPhase,
    RunRecord,
    RunStatus,
    ServerInfo,
    VersionCheck,
    now_iso,
    to_jsonable,
)
from .opencode_client import OpenCodeClient, OpenCodeClientError, compare_version
from .process import HOSTNAME, OpenCodeProcessManager, ProcessHandle, TerminationResult
from .reports import JSONLRenderer, append_jsonl, run_summary_row, write_json, write_manifest, write_run_record, write_summary
from .validation import validate_artifacts
from .worktree import WorktreeManager


@dataclass(slots=True)
class RunPaths:
    batch_dir: Path
    run_dir: Path
    events: Path
    status: Path
    children: Path
    todo: Path
    artifacts: Path


def make_batch_id() -> str:
    return "batch-" + time.strftime("%Y%m%d-%H%M%S") + f"-{uuid.uuid4().hex[:8]}"


class BatchRunner:
    def __init__(
        self,
        config: RunConfig,
        stream: TextIO,
        process_manager: OpenCodeProcessManager | None = None,
        client_factory: Callable[[str, str], OpenCodeClient] | None = None,
    ) -> None:
        self.config = config
        self.stream = stream
        self.process_manager = process_manager or OpenCodeProcessManager(config.opencode_version)
        self.client_factory = client_factory or (lambda base_url, password: OpenCodeClient(base_url, password))
        self.renderer = JSONLRenderer(stream) if config.json else None
        self.rich_renderer = RichLiveRenderer() if not config.json and not config.no_live else None
        self.live_store = LiveStateStore()
        self._emit_lock = threading.Lock()

    def run(self) -> list[RunRecord]:
        config = self.config
        repo = config.repo.resolve()
        output_root = config.output_dir.resolve()
        batch_id = make_batch_id()
        batch_dir = output_root / batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)
        worktree_root = config.worktree_root.resolve() if config.worktree_root else Path(tempfile.mkdtemp(prefix="eval-feia-"))
        manager = WorktreeManager(repo=repo, temp_root=worktree_root)
        base_commit = manager.resolve_base_commit(config.branch)
        manifest = BatchManifest(
            batch_id=batch_id,
            created_at=now_iso(),
            repo=str(repo),
            base_ref=config.branch,
            base_commit=base_commit,
            opencode_version=config.opencode_version,
            worktree_root=str(worktree_root),
        )
        write_manifest(batch_dir / "manifest.json", manifest)
        if config.concurrency == 1:
            records = [self._run_index(index, batch_dir, manager) for index in range(1, config.count + 1)]
        else:
            records = []
            with ThreadPoolExecutor(max_workers=config.concurrency) as executor:
                futures = [executor.submit(self._run_index, index, batch_dir, manager) for index in range(1, config.count + 1)]
                for future in as_completed(futures):
                    records.append(future.result())
            records.sort(key=lambda item: item.run_id)
        manifest.runs = [
            {
                "run_id": record.run_id,
                "run_root": str(Path(record.worktree.path).parent) if record.worktree else None,
                "worktree": to_jsonable(record.worktree) if record.worktree else {},
            }
            for record in records
        ]
        write_manifest(batch_dir / "manifest.json", manifest)
        rows = [run_summary_row(record, config.provider, config.model, config.opencode_version) for record in records]
        write_summary(batch_dir, rows)
        return records

    def _run_index(self, index: int, batch_dir: Path, manager: WorktreeManager) -> RunRecord:
        run_id = f"run-{index:03d}"
        paths = self._prepare_run_paths(batch_dir, run_id)
        record = RunRecord(run_id=run_id, batch_id=batch_dir.name, status=RunStatus.RUNNING)
        try:
            self._run_one(record, paths, manager)
        except Exception as exc:  # noqa: BLE001 - harness records failures instead of aborting batch
            record.status = RunStatus.FAILED
            if record.failure_class == FailureClass.NONE:
                record.failure_class = FailureClass.HARNESS_ERROR
            record.error_message = str(exc)
        finally:
            write_run_record(paths.run_dir, record)
        return record

    def _prepare_run_paths(self, batch_dir: Path, run_id: str) -> RunPaths:
        run_dir = batch_dir / "runs" / run_id
        artifacts = run_dir / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        for name in ["events.jsonl", "status_snapshots.jsonl", "children_snapshots.jsonl", "todo_snapshots.jsonl", "opencode.log", "diff.patch", "messages.json"]:
            (run_dir / name).touch()
        return RunPaths(
            batch_dir=batch_dir,
            run_dir=run_dir,
            events=run_dir / "events.jsonl",
            status=run_dir / "status_snapshots.jsonl",
            children=run_dir / "children_snapshots.jsonl",
            todo=run_dir / "todo_snapshots.jsonl",
            artifacts=artifacts,
        )

    def _run_one(self, record: RunRecord, paths: RunPaths, manager: WorktreeManager) -> None:
        config = self.config
        state = self.live_store.get(record.run_id)
        state.phase = RunPhase.WORKTREE
        record.worktree = manager.create_run_worktree(
            batch_id=record.batch_id,
            run_id=record.run_id,
            base_ref=config.branch,
            stream=self.stream,
            json_mode=config.json,
            emit_event=self._emit_worktree_event,
        )
        write_run_record(paths.run_dir, record)
        paths.run_dir.joinpath("prompt.txt").write_text(config.prompt)

        run_root = Path(record.worktree.path).parent
        run_home = run_root / "home"
        run_tmp = run_root / "tmp"
        port = config.base_port + int(record.run_id.split("-")[1]) - 1
        handle: ProcessHandle | None = None
        client: OpenCodeClient | None = None
        restart_count = 0
        start_elapsed_ms = 0
        try:
            while True:
                state.phase = RunPhase.SERVER_STARTING
                self._render_live(record)
                started = time.monotonic()
                if config.fake_server_url:
                    handle = _fake_process_handle(config.fake_server_url, port)
                else:
                    handle = self.process_manager.start(Path(record.worktree.path), run_home, run_tmp, port, paths.run_dir / "opencode.log")
                start_elapsed_ms = int((time.monotonic() - started) * 1000)
                client = self.client_factory(handle.base_url, handle.password)
                state.phase = RunPhase.SERVER_HEALTH
                try:
                    health = client.poll_health(config.server_start_timeout_seconds, config.health_poll_interval_seconds)
                except OpenCodeClientError as exc:
                    record.status = RunStatus.FAILED
                    record.failure_class = FailureClass.SERVER_UNHEALTHY
                    record.error_message = str(exc)
                    return
                record.server_health = health
                version_check = compare_version(config.opencode_version, health.reported_version)
                state.phase = RunPhase.CWD_CHECK
                cwd_check = (
                    client.check_cwd(Path(record.worktree.path))
                    if config.cwd_check
                    else CwdCheckResult(
                        expected_cwd=str(Path(record.worktree.path).resolve()),
                        actual_cwd=None,
                        status=CwdCheckStatus.SKIPPED,
                        source=None,
                    )
                )
                record.cwd_check = cwd_check
                server_info = ServerInfo(
                    run_id=record.run_id,
                    pid=handle.pid,
                    hostname=HOSTNAME,
                    port=port,
                    base_url=handle.base_url,
                    health_url=f"{handle.base_url}/global/health",
                    requested_version=config.opencode_version,
                    reported_version=health.reported_version,
                    version_check=version_check,
                    expected_cwd=cwd_check.expected_cwd,
                    actual_cwd=cwd_check.actual_cwd,
                    cwd_check=cwd_check.status,
                    restart_count=restart_count,
                    server_start_elapsed_ms=start_elapsed_ms,
                )
                record.server_info = server_info
                self._emit_server_info(server_info)
                write_run_record(paths.run_dir, record)
                mismatch_reason = self._mismatch_reason(version_check, cwd_check.status)
                if mismatch_reason is None:
                    break
                if not config.restart_on_mismatch:
                    record.status = RunStatus.FAILED
                    record.failure_class = FailureClass.SERVER_VERSION_MISMATCH if "version" in mismatch_reason else FailureClass.CWD_MISMATCH
                    return
                if restart_count >= config.max_server_restarts:
                    record.status = RunStatus.FAILED
                    record.failure_class = FailureClass.SERVER_RESTART_EXHAUSTED
                    state.phase = RunPhase.SERVER_RESTART_EXHAUSTED
                    return
                restart_count += 1
                state.phase = RunPhase.SERVER_MISMATCH
                self._emit({"type": "server_mismatch", "run_id": record.run_id, "reason": mismatch_reason})
                state.phase = RunPhase.SERVER_STOPPING
                termination = self._close_and_stop(client, handle)
                client = None
                handle = None
                record.server_restart_history.append(
                    RestartHistoryEntry(
                        attempt=restart_count,
                        pid=server_info.pid,
                        reason=mismatch_reason,
                        requested_version=config.opencode_version,
                        reported_version=health.reported_version,
                        expected_cwd=cwd_check.expected_cwd,
                        actual_cwd=cwd_check.actual_cwd,
                        terminated=termination.terminated,
                        killed=termination.killed,
                        elapsed_ms=termination.elapsed_ms,
                    )
                )
                state.phase = RunPhase.SERVER_RESTARTING
                self._emit({"type": "server_restart", "run_id": record.run_id, "action": "starting", "restart_count": restart_count})

            assert client is not None
            assert handle is not None
            if not config.fake_server_url and not handle.is_alive():
                record.status = RunStatus.FAILED
                record.failure_class = FailureClass.SERVER_UNHEALTHY
                record.error_message = "OpenCode server exited before session creation"
                return
            record.metrics.server_ready = True
            record.metrics.server_start_elapsed_ms = start_elapsed_ms
            record.metrics.server_restart_count = restart_count
            state.phase = RunPhase.SESSION_CREATE
            self._render_live(record)
            session_id = client.create_session(f"eval-feia {record.run_id}")
            state.phase = RunPhase.SSE_CONNECT
            sse_connected = threading.Event()
            sse_failed = threading.Event()
            stop_sse = threading.Event()
            record.live_summary = LiveSummary(sse_endpoint="/event", sse_listener_started_at=now_iso())
            sse_thread = threading.Thread(
                target=self._consume_sse,
                args=(client, record, paths, sse_connected, sse_failed, stop_sse),
                daemon=True,
            )
            sse_thread.start()
            if not self._wait_for_sse(record, sse_connected, sse_failed):
                record.status = RunStatus.FAILED
                record.failure_class = FailureClass.HARNESS_ERROR
                record.error_message = record.error_message or "SSE listener did not connect before prompt"
                stop_sse.set()
                return
            if sse_failed.is_set():
                record.status = RunStatus.FAILED
                record.failure_class = FailureClass.HARNESS_ERROR
                record.error_message = record.error_message or "SSE listener failed before prompt"
                stop_sse.set()
                return
            if not config.fake_server_url and not handle.is_alive():
                record.status = RunStatus.FAILED
                record.failure_class = FailureClass.SERVER_UNHEALTHY
                record.error_message = "OpenCode server exited before prompt submission"
                return
            state.phase = RunPhase.PROMPT_SEND
            record.live_summary.prompt_sent_at = now_iso()
            client.send_prompt_async(session_id, config.prompt, config.provider, config.model, config.skill)
            record.metrics.prompt_sent = True
            state.phase = RunPhase.RUNNING
            self._poll_until_idle(client, session_id, record, paths, state)
            stop_sse.set()
            sse_thread.join(timeout=1)
            record.live_summary.final_phase = RunPhase.COMPLETED
            record.metrics.opencode_completed = True
            record.metrics.idle_quiet_ms = int(config.idle_quiet_seconds * 1000)
            record.metrics.total_operational_ms = int(state.elapsed_seconds * 1000)
            write_json(paths.run_dir / "messages.json", client.messages(session_id))
            paths.run_dir.joinpath("diff.patch").write_text(client.diff(session_id))
            validation = validate_artifacts(Path(record.worktree.path))
            if validation.artifact_path:
                artifact = Path(validation.artifact_path)
                if artifact.exists():
                    copied = paths.artifacts / artifact.name
                    shutil.copy2(artifact, copied)
                    validation.artifact_path = str(copied)
            write_json(paths.run_dir / "validation.json", validation)
            record.validation = validation
            record.metrics = merge_validation_metrics(metrics_from_events(paths.events), validation)
            record.metrics.server_ready = True
            record.metrics.prompt_sent = True
            record.metrics.opencode_completed = True
            record.metrics.server_restart_count = restart_count
            record.metrics.server_start_elapsed_ms = start_elapsed_ms
            record.status = RunStatus.COMPLETED if validation.validation_passed else RunStatus.FAILED
            record.failure_class = FailureClass.NONE if validation.validation_passed else FailureClass.VALIDATION_FAILURE
            self._emit({"type": "run_completed" if validation.validation_passed else "run_failed", "run_id": record.run_id})
        finally:
            if client is not None or handle is not None:
                self._close_and_stop(client, handle)

    def _emit(self, payload: dict[str, object]) -> None:
        with self._emit_lock:
            if self.renderer:
                self.renderer.emit(payload)
            else:
                if payload.get("type") == "server_info":
                    print(
                        f"[{payload['run_id']}] server: pid={payload.get('pid')} port={payload.get('port')} "
                        f"version={payload.get('version_check')} cwd={payload.get('cwd_check')} restarts={payload.get('restart_count')}",
                        file=self.stream,
                        flush=True,
                    )

    def _emit_worktree_event(self, payload: dict[str, Any]) -> None:
        with self._emit_lock:
            if self.renderer:
                self.renderer.emit(payload)
            else:
                print(f"[{payload['run_id']}] worktree: {payload['path']}", file=self.stream, flush=True)

    def _emit_server_info(self, info: ServerInfo) -> None:
        self._emit(
            {
                "type": "server_info",
                "run_id": info.run_id,
                "pid": info.pid,
                "hostname": info.hostname,
                "port": info.port,
                "base_url": info.base_url,
                "requested_version": info.requested_version,
                "reported_version": info.reported_version,
                "version_check": str(info.version_check),
                "expected_cwd": info.expected_cwd,
                "actual_cwd": info.actual_cwd,
                "cwd_check": str(info.cwd_check),
                "restart_count": info.restart_count,
            }
        )

    @staticmethod
    def _mismatch_reason(version_check: VersionCheck, cwd_status: CwdCheckStatus) -> str | None:
        if version_check == VersionCheck.MISMATCH:
            return "version_mismatch"
        if cwd_status == CwdCheckStatus.MISMATCH:
            return "cwd_mismatch"
        if cwd_status == CwdCheckStatus.UNKNOWN:
            return "cwd_unknown"
        return None

    def _render_live(self, record: RunRecord) -> None:
        if self.rich_renderer is None:
            return
        self.rich_renderer.render_once(self.live_store.states.values())
        record.live_summary.renderer_refresh_count = self.rich_renderer.refresh_count

    def _close_and_stop(self, client: OpenCodeClient | None, handle: ProcessHandle | None) -> TerminationResult:
        if client is not None:
            client.close()
        if handle is None or self.config.fake_server_url:
            return TerminationResult(terminated=False, killed=False, elapsed_ms=0)
        return self.process_manager.stop(handle)

    @staticmethod
    def _wait_for_sse(record: RunRecord, connected: threading.Event, failed: threading.Event) -> bool:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if failed.is_set():
                return False
            if connected.is_set():
                time.sleep(0.05)
                if failed.is_set():
                    return False
                return True
            time.sleep(0.01)
        record.error_message = record.error_message or "SSE listener did not connect before prompt"
        return False

    def _consume_sse(
        self,
        client: OpenCodeClient,
        record: RunRecord,
        paths: RunPaths,
        connected: threading.Event,
        failed: threading.Event,
        stop: threading.Event,
    ) -> None:
        try:
            def mark_connected() -> None:
                record.live_summary.sse_connected_at = now_iso()
                connected.set()

            stream = client.stream_sse(record.live_summary.sse_endpoint or "/event", on_connected=mark_connected)
            with paths.events.open("a") as events_file:
                for event in stream:
                    if stop.is_set():
                        break
                    payload = event.data if isinstance(event.data, dict) else {"data": event.data}
                    payload.setdefault("type", event.event or payload.get("type") or "sse")
                    append_jsonl(events_file, payload)
                    record.live_summary.total_sse_events += 1
                    timestamp = now_iso()
                    record.live_summary.first_event_at = record.live_summary.first_event_at or timestamp
                    record.live_summary.last_event_at = timestamp
                    self.live_store.update_from_sse(record.run_id, event.event, payload)
            if not stop.is_set():
                failed.set()
                record.error_message = record.error_message or "SSE stream ended before prompt/run completion"
        except Exception as exc:  # noqa: BLE001 - surfaced via record for harness diagnostics
            record.live_summary.sse_parser_errors += 1
            failed.set()
            record.error_message = record.error_message or f"SSE failed: {exc}"

    def _poll_until_idle(self, client: OpenCodeClient, session_id: str, record: RunRecord, paths: RunPaths, state: LiveState) -> None:
        quiet_started: float | None = None
        last_sse_count = record.live_summary.total_sse_events
        last_todo_fingerprint: str | None = None
        deadline = time.monotonic() + self.config.hard_timeout_seconds
        while time.monotonic() < deadline:
            status = client.session_status()
            children = client.children(session_id)
            todo = client.todo(session_id)
            record.live_summary.total_status_polls += 1
            record.live_summary.total_children_polls += 1
            record.live_summary.total_todo_polls += 1
            with paths.status.open("a") as file:
                append_jsonl(file, status if isinstance(status, dict) else {"value": status})
            with paths.children.open("a") as file:
                append_jsonl(file, children if isinstance(children, dict) else {"children": children})
            with paths.todo.open("a") as file:
                append_jsonl(file, todo if isinstance(todo, dict) else {"items": todo})
            self.live_store.update_from_polls(record.run_id, status, children, todo)
            todo_fingerprint = json.dumps(todo, sort_keys=True, default=str)
            stable = record.live_summary.total_sse_events == last_sse_count and todo_fingerprint == last_todo_fingerprint
            if self.live_store.all_idle(status, children) and stable:
                if quiet_started is None:
                    quiet_started = time.monotonic()
                    state.phase = RunPhase.IDLE_WAIT
                state.quiet_seconds = time.monotonic() - quiet_started
                if state.quiet_seconds >= self.config.idle_quiet_seconds:
                    return
            else:
                quiet_started = None
                state.quiet_seconds = 0
            last_sse_count = record.live_summary.total_sse_events
            last_todo_fingerprint = todo_fingerprint
            if self.renderer:
                self.renderer.emit(state.to_progress_event())
            self._render_live(record)
            time.sleep(min(0.1, self.config.health_poll_interval_seconds))
        record.status = RunStatus.TIMEOUT
        record.failure_class = FailureClass.TIMEOUT
        record.metrics.timeout = True
        raise TimeoutError("run timed out")


def _fake_process_handle(base_url: str, port: int) -> ProcessHandle:
    class FakeProcess:
        pid: int = 99999

        def poll(self) -> int | None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

    return ProcessHandle(
        process=FakeProcess(),
        port=port,
        hostname=HOSTNAME,
        base_url=base_url.rstrip("/"),
        password="test-password",
        command=[],
    )
