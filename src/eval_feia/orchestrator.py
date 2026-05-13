from __future__ import annotations

import tempfile
import threading
import time
import shutil
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, nullcontext
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Protocol, cast

from .cleanup import MARKER_FILE, ROOT_MARKER_FILE
from .live import LiveRunState, ProgressSink, RenderingProgressSink, RichLiveRenderer, RichProgressSink, has_active_status, is_idle
from .metrics import apply_validation_metrics, update_metrics_from_event, update_metrics_from_snapshots
from .models import (
    BatchSpec,
    CwdCheck,
    ProgressEvent,
    RunRecord,
    RunSpec,
    ServerInfo,
    HealthCheck,
    jsonable,
    utc_now_iso,
)
from .opencode_client import OpenCodeClient, check_version
from .process import HOSTNAME, ProcessManager
from .reports import append_jsonl, run_summary_row, write_json, write_summary
from .sse import SseEvent
from .validation import validate_autogen_config
from .worktree import create_worktree, resolve_base_commit


class ServerHandle(Protocol):
    password: str
    pid: int
    returncode: int | None

    def is_alive(self) -> bool: ...


class ProcessManagerLike(Protocol):
    def start(self, *, worktree: Path, home: Path, tmp: Path, log_path: Path, version: str, port: int) -> ServerHandle: ...

    def stop(self, server: ServerHandle, grace_seconds: float = 3.0) -> dict[str, object]: ...


class SseConnectionLike(Protocol):
    connected: bool

    def events(self, limit: int | None = None) -> Iterator[SseEvent]: ...


class OpenCodeClientLike(Protocol):
    def close(self) -> None: ...

    def poll_health(self, timeout_seconds: float, interval_seconds: float) -> HealthCheck: ...

    def verify_cwd(self, expected: Path) -> CwdCheck: ...

    def create_session(self, title: str) -> str: ...

    def open_sse(self, endpoint: str = "/event") -> AbstractContextManager[SseConnectionLike]: ...

    def send_prompt(self, session_id: str, prompt: str, skill: str, provider: str | None = None, model: str | None = None) -> str: ...

    def status(self) -> object: ...

    def children(self, session_id: str) -> object: ...

    def todo(self, session_id: str) -> object: ...

    def diff(self, session_id: str) -> str: ...

    def messages(self, session_id: str) -> object: ...


def make_batch_id() -> str:
    return time.strftime("batch-%Y%m%d-%H%M%S")


def can_submit_prompt(
    *,
    worktree_created: bool,
    server_process_alive: bool,
    health_ok: bool,
    server_info_emitted: bool,
    version_check: str,
    cwd_check: str,
    session_created: bool,
    sse_connected: bool,
) -> tuple[bool, list[str]]:
    missing: list[str] = []
    if not worktree_created:
        missing.append("worktree_created")
    if not server_process_alive:
        missing.append("server_process_alive")
    if not health_ok:
        missing.append("health_ok")
    if not server_info_emitted:
        missing.append("server_info_emitted")
    if version_check == "mismatch":
        missing.append("version_check")
    if cwd_check not in {"ok", "skipped"}:
        missing.append("cwd_check")
    if not session_created:
        missing.append("session_created")
    if not sse_connected:
        missing.append("sse_connected")
    return not missing, missing


class RunWorker:
    def __init__(
        self,
        spec: RunSpec,
        sink: ProgressSink | None = None,
        process_manager: object = None,
        client_factory: Callable[..., object] = OpenCodeClient,
        state: LiveRunState | None = None,
    ) -> None:
        self.spec: RunSpec = spec
        self.sink: ProgressSink = sink or RichProgressSink()
        self.process_manager: ProcessManagerLike = cast(ProcessManagerLike, process_manager or ProcessManager())
        self.client_factory: Callable[..., object] = client_factory
        self.state: LiveRunState = state or LiveRunState(run_id=spec.run_id, port=spec.port)
        self.events_path: Path = spec.run_dir / "events.jsonl"
        self.status_path: Path = spec.run_dir / "status_snapshots.jsonl"
        self.children_path: Path = spec.run_dir / "children_snapshots.jsonl"
        self.todo_path: Path = spec.run_dir / "todo_snapshots.jsonl"
        self.messages_path: Path = spec.run_dir / "messages.json"

    def emit(self, kind: str, **data: object) -> None:
        event = ProgressEvent(kind, self.spec.run_id, data)
        self.sink.emit(event)

    def set_phase(self, phase: str, note: str = "") -> None:
        self.state.phase = phase
        self.state.note = note
        self.emit("run_progress", phase=phase, note=note, msg=self.state.message_count, tool=self.state.tool_call_count, child=self.state.child_session_count, todo=self.state.todo_status, quiet=int(self.state.quiet_seconds), elapsed_ms=int(self.state.elapsed_seconds * 1000))

    def run(self) -> RunRecord:
        spec = self.spec
        record = RunRecord(run_id=spec.run_id, batch_id=spec.batch_id)
        server: ServerHandle | None = None
        client: OpenCodeClientLike | None = None
        started = time.monotonic()
        spec.run_dir.mkdir(parents=True, exist_ok=True)
        (spec.run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        _ = (spec.run_dir / "prompt.txt").write_text(spec.prompt, encoding="utf-8")
        try:
            self.set_phase("worktree")
            worktree = create_worktree(spec.repo, spec.worktree_path, spec.branch, spec.base_commit)
            spec.temp_run_dir.mkdir(parents=True, exist_ok=True)
            _ = (spec.temp_run_dir / MARKER_FILE).write_text(spec.run_id + "\n", encoding="utf-8")
            record.worktree = worktree
            record.temp_run_dir = str(spec.temp_run_dir)
            record.status = "worktree"
            self.state.worktree_path = worktree.path
            self.emit("worktree_created", path=worktree.path)
            write_json(spec.run_dir / "run.json", record.to_dict())

            server, client, server_info = self._ready_server(record)
            record.metrics.server_ready = True
            record.metrics.server_start_elapsed_ms = server_info.server_start_elapsed_ms
            record.metrics.server_restart_count = server_info.restart_count
            self.set_phase("session-create")
            session_id = client.create_session(f"eval-feia {spec.run_id}")
            record.session_id = session_id
            self.set_phase("sse-connect")
            stop_sse = threading.Event()
            with client.open_sse("/event") as sse:
                record.live_summary.sse_endpoint = "/event"
                record.live_summary.sse_connected_at = utc_now_iso()
                record.live_summary.sse_listener_started_at = record.live_summary.sse_connected_at
                sse_reader = threading.Thread(target=self._drain_sse, args=(record, sse, stop_sse), daemon=True)
                sse_reader.start()
                ok, missing = can_submit_prompt(
                    worktree_created=bool(record.worktree.path),
                    server_process_alive=_server_alive(server),
                    health_ok=record.server_health.ok,
                    server_info_emitted=bool(record.server_info),
                    version_check=server_info.version_check,
                    cwd_check=record.cwd_check.result,
                    session_created=bool(record.session_id),
                    sse_connected=sse.connected,
                )
                if not ok:
                    raise RuntimeError(f"prompt gate failed: {', '.join(missing)}")
                self.set_phase("prompt-send")
                method = client.send_prompt(session_id, spec.prompt, spec.skill, spec.provider, spec.model)
                record.prompt_sent = True
                record.metrics.prompt_sent = True
                record.live_summary.prompt_sent_at = utc_now_iso()
                self.state.last_activity = time.monotonic()
                self.state.quiet_seconds = 0
                append_jsonl(self.events_path, {"type": "prompt_sent", "method": method, "run_id": spec.run_id})
                self.set_phase("running")
                try:
                    self._monitor(record, client, session_id)
                finally:
                    time.sleep(0.1)
                    stop_sse.set()
            sse_reader.join(timeout=2)
            self._collect_diff(client, session_id)
            record.validation = validate_autogen_config(spec.worktree_path)
            self._copy_validation_artifact(record)
            self._collect_messages(client, session_id)
            write_json(spec.run_dir / "validation.json", record.validation)
            apply_validation_metrics(record.metrics, record.validation)
            record.status = "completed" if record.validation.validation_passed else "failed"
            record.failure_class = "none" if record.validation.validation_passed else "validation_failure"
            record.metrics.opencode_completed = True
            record.completed_at = utc_now_iso()
            self.set_phase(record.status)
            event_type = "run_completed" if record.status == "completed" else "run_failed"
            self.emit(event_type, status=record.status, failure_class=record.failure_class)
        except TimeoutError as exc:
            record.status = "timeout"
            record.failure_class = "timeout"
            record.error_message = str(exc)
            record.metrics.timeout = True
            record.completed_at = utc_now_iso()
            self.set_phase("timeout", str(exc)[:40])
            self.emit("run_failed", status=record.status, failure_class=record.failure_class, error_message=record.error_message)
        except Exception as exc:
            if record.failure_class == "none":
                record.failure_class = "harness_error"
            record.status = "failed"
            record.error_message = str(exc)
            record.metrics.harness_error = record.failure_class == "harness_error"
            record.completed_at = utc_now_iso()
            self.set_phase("failed", str(exc)[:40])
            self.emit("run_failed", status=record.status, failure_class=record.failure_class, error_message=record.error_message)
        finally:
            record.metrics.total_operational_ms = int((time.monotonic() - started) * 1000)
            record.live_summary.final_phase = self.state.phase
            if client is not None:
                client.close()
            if server is not None and _server_alive(server):
                _ = self.process_manager.stop(server)
            write_json(spec.run_dir / "run.json", record.to_dict())
        return record

    def _ready_server(self, record: RunRecord) -> tuple[ServerHandle, OpenCodeClientLike, ServerInfo]:
        spec = self.spec
        server: ServerHandle | None = None
        client: OpenCodeClientLike | None = None
        for restart_count in range(spec.max_server_restarts + 1):
            server = None
            client = None
            self.set_phase("server-starting")
            try:
                if restart_count:
                    self.emit("server_restart", action="starting", port=spec.port, restart_count=restart_count)
                start_time = time.monotonic()
                server = self.process_manager.start(
                    worktree=spec.worktree_path,
                    home=spec.home_dir,
                    tmp=spec.tmp_dir,
                    log_path=spec.run_dir / "opencode.log",
                    version=spec.opencode_version,
                    port=spec.port,
                )
                base_url = f"http://{HOSTNAME}:{spec.port}"
                raw_client = self.client_factory(base_url=base_url, password=server.password, directory=spec.worktree_path)
                if raw_client is None:
                    raise RuntimeError("client factory returned no client")
                client = cast(OpenCodeClientLike, raw_client)
                self.set_phase("server-health")
                health = client.poll_health(spec.server_start_timeout_seconds, spec.health_poll_interval_seconds)
                record.server_health = health
                if not health.ok:
                    record.failure_class = "server_unhealthy"
                    _ = self.process_manager.stop(server)
                    client.close()
                    raise RuntimeError("OpenCode server did not become healthy")
                version_result = check_version(spec.opencode_version, health.version)
                self.set_phase("cwd-check")
                if spec.cwd_check:
                    cwd = client.verify_cwd(spec.worktree_path)
                else:
                    cwd = CwdCheck(result="skipped", expected_cwd=str(spec.worktree_path.resolve()), actual_cwd=None, source=None)
                record.cwd_check = cwd
                server_info = ServerInfo(
                    run_id=spec.run_id,
                    pid=server.pid,
                    hostname=HOSTNAME,
                    port=spec.port,
                    base_url=base_url,
                    health_url=f"{base_url}/global/health",
                    requested_version=spec.opencode_version,
                    reported_version=health.version,
                    version_check=version_result,
                    expected_cwd=str(spec.worktree_path.resolve()),
                    actual_cwd=cwd.actual_cwd,
                    cwd_check=cwd.result,
                    restart_count=restart_count,
                    server_start_elapsed_ms=int((time.monotonic() - start_time) * 1000),
                )
                server_info_data = cast(dict[str, object], jsonable(server_info))
                record.server_info = server_info_data
                record.metrics.server_restart_count = restart_count
                self.state.health = "ok"
                self.state.cwd = cwd.result
                self.state.restart_count = restart_count
                self.set_phase("server-info")
                self.emit("server_info", **server_info_data)
                cwd_failed = spec.cwd_check and cwd.result != "ok"
                mismatch = version_result == "mismatch" or cwd_failed
                if not mismatch:
                    self.set_phase("server-ready")
                    return server, client, server_info
                reason = "version_mismatch" if version_result == "mismatch" else ("cwd_unknown" if cwd.result == "unknown" else "cwd_mismatch")
                self.emit("server_mismatch", reason=reason, expected=spec.opencode_version if reason == "version_mismatch" else server_info.expected_cwd, actual=health.version if reason == "version_mismatch" else cwd.actual_cwd)
                if not spec.restart_on_mismatch:
                    record.failure_class = "server_version_mismatch" if version_result == "mismatch" else "cwd_mismatch"
                    _ = self.process_manager.stop(server)
                    client.close()
                    raise RuntimeError(f"server mismatch: {reason}")
                if restart_count >= spec.max_server_restarts:
                    record.failure_class = "server_restart_exhausted"
                    self.set_phase("server-restart-exhausted")
                    _ = self.process_manager.stop(server)
                    client.close()
                    raise RuntimeError(f"server restart exhausted after {restart_count} restarts")
                self.set_phase("server-stopping")
                stop_result = self.process_manager.stop(server)
                history = {
                    "attempt": restart_count + 1,
                    "pid": server.pid,
                    "reason": reason,
                    "requested_version": spec.opencode_version,
                    "reported_version": health.version,
                    "expected_cwd": server_info.expected_cwd,
                    "actual_cwd": cwd.actual_cwd,
                    **stop_result,
                }
                record.server_restart_history.append(history)
                self.emit("server_restart", action="stopping", pid=server.pid, restart_count=restart_count + 1)
                client.close()
            except Exception:
                if client is not None:
                    client.close()
                if server is not None and _server_alive(server):
                    _ = self.process_manager.stop(server)
                raise
        raise RuntimeError("unreachable server readiness state")

    def _monitor(self, record: RunRecord, client: OpenCodeClientLike, session_id: str) -> None:
        spec = self.spec
        deadline = time.monotonic() + spec.hard_timeout_seconds
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("run exceeded hard timeout")
            status = client.status()
            children = client.children(session_id)
            todo = client.todo(session_id)
            record.live_summary.total_status_polls += 1
            record.live_summary.total_children_polls += 1
            record.live_summary.total_todo_polls += 1
            append_jsonl(self.status_path, {"run_id": spec.run_id, "status": status})
            append_jsonl(self.children_path, {"run_id": spec.run_id, "children": children})
            append_jsonl(self.todo_path, {"run_id": spec.run_id, "todo": todo})
            self.state.update_from_status(status)
            self.state.update_children(children)
            self.state.update_todo(todo)
            update_metrics_from_snapshots(record.metrics, children, todo)
            quiet = max(0.0, time.monotonic() - self.state.last_activity)
            self.state.quiet_seconds = quiet
            self.emit("run_progress", phase="running", msg=self.state.message_count, tool=self.state.tool_call_count, child=self.state.child_session_count, todo=self.state.todo_status, quiet=int(quiet), elapsed_ms=int(self.state.elapsed_seconds * 1000))
            if is_idle(status, children, quiet, spec.idle_quiet_seconds, recent_events=False):
                self.set_phase("idle-wait")
                record.metrics.idle_quiet_ms = int(quiet * 1000)
                return
            if not has_active_status(status) and not has_active_status(children) and spec.idle_quiet_seconds <= 0:
                return
            time.sleep(min(1.0, max(0.01, spec.idle_quiet_seconds / 2)))

    def _collect_diff(self, client: OpenCodeClientLike, session_id: str) -> None:
        try:
            diff = client.diff(session_id)
        except Exception:
            diff = ""
        _ = (self.spec.run_dir / "diff.patch").write_text(diff, encoding="utf-8")

    def _record_sse_event(self, record: RunRecord, event: SseEvent) -> None:
        parsed = cast(object, event.parsed)
        payload = {"event": event.event, "data": event.data, "parsed": parsed, "parse_error": event.parse_error}
        append_jsonl(self.events_path, payload)
        now = utc_now_iso()
        if record.live_summary.first_event_at is None:
            record.live_summary.first_event_at = now
        record.live_summary.last_event_at = now
        record.live_summary.total_sse_events += 1
        self.state.last_activity = time.monotonic()
        if event.parse_error:
            record.live_summary.sse_parser_errors += 1
        if isinstance(parsed, dict):
            parsed_event = cast(dict[str, object], parsed)
            self.state.apply_event(parsed_event)
            update_metrics_from_event(record.metrics, parsed_event)

    def _drain_sse(self, record: RunRecord, sse: SseConnectionLike, stop: threading.Event) -> None:
        try:
            for event in sse.events():
                if stop.is_set():
                    return
                self._record_sse_event(record, event)
        except Exception:
            if not stop.is_set():
                record.live_summary.sse_parser_errors += 1

    def _copy_validation_artifact(self, record: RunRecord) -> None:
        if not record.validation.artifact_path:
            return
        source = (self.spec.worktree_path / record.validation.artifact_path).resolve()
        try:
            _ = source.relative_to(self.spec.worktree_path.resolve())
        except ValueError:
            return
        target = self.spec.run_dir / "artifacts" / record.validation.artifact_path
        target.parent.mkdir(parents=True, exist_ok=True)
        _ = shutil.copy2(source, target)

    def _collect_messages(self, client: OpenCodeClientLike, session_id: str) -> None:
        try:
            messages = client.messages(session_id)
        except Exception:
            messages = []
        write_json(self.messages_path, messages)


def _server_alive(server: ServerHandle) -> bool:
    return server.is_alive()


class BatchRunner:
    def __init__(
        self,
        spec: BatchSpec,
        sink: ProgressSink | None = None,
        process_manager: object = None,
        client_factory: Callable[..., object] = OpenCodeClient,
    ) -> None:
        self.spec: BatchSpec = spec
        self.sink: ProgressSink = sink or RichProgressSink()
        self.process_manager: ProcessManagerLike = cast(ProcessManagerLike, process_manager or ProcessManager())
        self.client_factory: Callable[..., object] = client_factory
        self.batch_id: str = spec.batch_id or make_batch_id()
        self.repo: Path = spec.repo.resolve()
        self.output_dir: Path = spec.output_dir.resolve()
        self.batch_dir: Path = self.output_dir / self.batch_id
        self.temp_root: Path = (spec.worktree_root.resolve() if spec.worktree_root else Path(tempfile.gettempdir()) / "eval-feia") / self.batch_id

    def build_run_specs(self) -> list[RunSpec]:
        base_commit = resolve_base_commit(self.repo, self.spec.branch)
        specs: list[RunSpec] = []
        for index in range(1, self.spec.count + 1):
            run_id = f"run-{index:03d}"
            run_dir = self.batch_dir / "runs" / run_id
            temp_run_dir = self.temp_root / run_id
            specs.append(
                RunSpec(
                    batch_id=self.batch_id,
                    run_id=run_id,
                    repo=self.repo,
                    branch=self.spec.branch,
                    base_commit=base_commit,
                    prompt=self.spec.prompt,
                    skill=self.spec.skill,
                    output_dir=self.output_dir,
                    batch_dir=self.batch_dir,
                    run_dir=run_dir,
                    temp_run_dir=temp_run_dir,
                    worktree_path=temp_run_dir / "worktree",
                    home_dir=temp_run_dir / "home",
                    tmp_dir=temp_run_dir / "tmp",
                    port=self.spec.base_port + index - 1,
                    opencode_version=self.spec.opencode_version,
                    provider=self.spec.provider,
                    model=self.spec.model,
                    server_start_timeout_seconds=self.spec.server_start_timeout_seconds,
                    health_poll_interval_seconds=self.spec.health_poll_interval_seconds,
                    cwd_check=self.spec.cwd_check,
                    restart_on_mismatch=self.spec.restart_on_mismatch,
                    max_server_restarts=self.spec.max_server_restarts,
                    idle_quiet_seconds=self.spec.idle_quiet_seconds,
                    hard_timeout_seconds=self.spec.hard_timeout_seconds,
                )
            )
        return specs

    def run(self) -> tuple[list[RunRecord], Path]:
        self.batch_dir.mkdir(parents=True, exist_ok=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)
        _ = (self.temp_root / ROOT_MARKER_FILE).write_text(self.batch_id + "\n", encoding="utf-8")
        specs = self.build_run_specs()
        manifest: dict[str, object] = {
            "batch_id": self.batch_id,
            "created_at": utc_now_iso(),
            "repo": str(self.repo),
            "base_ref": self.spec.branch,
            "base_commit": specs[0].base_commit if specs else "",
            "opencode_version": self.spec.opencode_version,
            "worktree_root": str(self.temp_root),
            "runs": [],
        }
        write_json(self.batch_dir / "manifest.json", manifest)
        records: list[RunRecord] = []
        states = {spec.run_id: LiveRunState(run_id=spec.run_id, port=spec.port) for spec in specs}
        live_context = RichLiveRenderer(list(states.values())) if self.spec.live and not self.spec.json else nullcontext(None)
        with live_context as renderer, ThreadPoolExecutor(max_workers=max(1, self.spec.concurrency)) as executor:
            sink = RenderingProgressSink(self.sink, renderer) if renderer is not None else self.sink
            futures = {
                executor.submit(
                    RunWorker(spec, sink, self.process_manager, self.client_factory, states[spec.run_id]).run
                ): spec
                for spec in specs
            }
            for future in as_completed(futures):
                records.append(future.result())
        records.sort(key=lambda item: item.run_id)
        specs_by_id = {spec.run_id: spec for spec in specs}
        manifest_runs: list[dict[str, object]] = []
        for record in records:
            run_spec = specs_by_id[record.run_id]
            manifest_runs.append(
                {
                    "run_id": record.run_id,
                    "worktree": {
                        "path": record.worktree.path,
                        "base_ref": record.worktree.base_ref,
                        "base_commit": record.worktree.base_commit,
                        "created_at": record.worktree.created_at,
                    },
                    "status": record.status,
                    "failure_class": record.failure_class,
                    "temp_run_dir": str(run_spec.temp_run_dir),
                }
            )
        manifest["runs"] = manifest_runs
        write_json(self.batch_dir / "manifest.json", manifest)
        rows = [
            run_summary_row(
                record,
                provider=specs_by_id[record.run_id].provider,
                model=specs_by_id[record.run_id].model,
                opencode_version=specs_by_id[record.run_id].opencode_version,
                port=specs_by_id[record.run_id].port,
            )
            for record in records
        ]
        write_summary(self.batch_dir, rows)
        return records, self.batch_dir
