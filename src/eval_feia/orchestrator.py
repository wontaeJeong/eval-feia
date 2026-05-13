from __future__ import annotations

import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, TextIO

from .live import JsonlWriter, LiveState, idle_complete
from .metrics import apply_validation, update_metrics_from_event, update_metrics_from_todo
from .models import (
    BatchOptions,
    CwdCheck,
    FailureClass,
    HealthCheck,
    LiveSummary,
    Metrics,
    RunResult,
    ServerInfo,
    ValidationResult,
    dataclass_to_json,
    now_iso,
)
from .opencode_client import OpenCodeClient
from .process import HOSTNAME, USERNAME, OpenCodeProcessManager, ProcessHandle, build_opencode_command, build_server_env, generate_password
from .reports import create_manifest, write_json, write_summary
from .sse import SseEvent, SseListener
from .validation import validate_worktree
from .worktree import create_worktree, resolve_base_commit


class ProgressEmitter:
    def __init__(self, json_mode: bool, stream: TextIO, console_print: Callable[[str], None]) -> None:
        self.json_mode = json_mode
        self.writer = JsonlWriter(stream) if json_mode else None
        self.console_print = console_print
        self._lock = threading.Lock()

    def emit(self, event: dict[str, Any]) -> None:
        with self._lock:
            if self.writer is not None:
                self.writer.write(event)
            else:
                event_type = event.get("type", "event")
                run_id = event.get("run_id", "-")
                if event_type == "worktree_created":
                    self.console_print(f"{run_id} | worktree | {event.get('path')}")
                elif event_type == "server_info":
                    self.console_print(
                        f"{run_id} | server-info | pid={event.get('pid')} port={event.get('port')} "
                        f"version={event.get('version_check')} cwd={event.get('cwd_check')} restarts={event.get('restart_count')}"
                    )
                elif event_type in {"server_mismatch", "server_restart", "run_completed", "run_failed"}:
                    self.console_print(f"{run_id} | {event_type} | {event.get('reason') or event.get('status') or event.get('action') or ''}")


def batch_id() -> str:
    return "batch-" + time.strftime("%Y%m%d-%H%M%S")


def prompt_gate(
    worktree_created: bool,
    process_alive: bool,
    health: HealthCheck | None,
    server_info: ServerInfo | None,
    cwd: CwdCheck | None,
    session_id: str | None,
    sse_connected: bool,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not worktree_created:
        failures.append("worktree not created")
    if not process_alive:
        failures.append("server process not alive")
    if health is None or not health.ok:
        failures.append("health not ok")
    if server_info is None:
        failures.append("server info not emitted")
    if server_info is not None and server_info.version_check == "mismatch":
        failures.append("version mismatch")
    if cwd is not None and cwd.cwd_check == "mismatch":
        failures.append("cwd mismatch")
    if session_id is None:
        failures.append("session not created")
    if not sse_connected:
        failures.append("SSE not connected")
    return not failures, failures


class RunExecutor:
    def __init__(
        self,
        options: BatchOptions,
        batch: str,
        batch_dir: Path,
        base_commit: str,
        emitter: ProgressEmitter,
        process_manager: OpenCodeProcessManager | None = None,
        client_factory: Callable[[str, str, str, Path], OpenCodeClient] | None = None,
    ) -> None:
        self.options = options
        self.batch = batch
        self.batch_dir = batch_dir
        self.base_commit = base_commit
        self.emitter = emitter
        self.process_manager = process_manager or OpenCodeProcessManager()
        self.client_factory = client_factory or (lambda base_url, username, password, directory: OpenCodeClient(base_url, username, password, directory))

    def run(self, index: int) -> RunResult:
        run_id = f"run-{index:03d}"
        port = self.options.base_port + index - 1
        run_results_dir = self.batch_dir / "runs" / run_id
        run_results_dir.mkdir(parents=True, exist_ok=True)
        run_root = (self.options.worktree_root or Path(tempfile.gettempdir()) / "eval-feia") / self.batch / run_id
        run_home = run_root / "home"
        run_tmp = run_root / "tmp"
        run_logs = run_root / "logs"
        for path in (run_home, run_tmp, run_logs, run_results_dir / "artifacts"):
            path.mkdir(parents=True, exist_ok=True)
        events_path = run_results_dir / "events.jsonl"
        status_path = run_results_dir / "status_snapshots.jsonl"
        children_path = run_results_dir / "children_snapshots.jsonl"
        todo_path = run_results_dir / "todo_snapshots.jsonl"
        prompt_path = run_results_dir / "prompt.txt"
        prompt_path.write_text(self.options.prompt, encoding="utf-8")
        events_stream = events_path.open("a", encoding="utf-8")
        status_stream = status_path.open("a", encoding="utf-8")
        children_stream = children_path.open("a", encoding="utf-8")
        todo_stream = todo_path.open("a", encoding="utf-8")
        event_writer = JsonlWriter(events_stream)
        status_writer = JsonlWriter(status_stream)
        children_writer = JsonlWriter(children_stream)
        todo_writer = JsonlWriter(todo_stream)
        live = LiveState(run_id=run_id, port=port)
        summary = LiveSummary()
        metrics = Metrics()
        health: HealthCheck | None = None
        cwd: CwdCheck | None = None
        server_info: ServerInfo | None = None
        restart_history: list[dict[str, Any]] = []
        handle: ProcessHandle | None = None
        client: OpenCodeClient | None = None
        listener: SseListener | None = None
        started_at = time.monotonic()
        try:
            live.set_phase("worktree")
            worktree = create_worktree(
                self.options.repo,
                run_root,
                self.options.branch,
                self.base_commit,
                on_created=lambda path: self._emit_worktree(run_id, path),
            )
            live.worktree_path = worktree.path
            password = generate_password()
            restart_count = 0
            while True:
                live.restart_count = restart_count
                live.set_phase("server-starting")
                command = build_opencode_command(self.options.opencode_version, port)
                env = build_server_env(run_home, run_tmp, password)
                handle = self.process_manager.start(command, Path(worktree.path), env, run_results_dir / "opencode.log", port=port)
                base_url = handle.base_url
                client = self.client_factory(base_url, USERNAME, password, Path(worktree.path))
                live.set_phase("server-health")
                server_start = time.monotonic()
                health = client.wait_health(
                    self.options.opencode_version,
                    self.options.server_start_timeout_seconds,
                    self.options.health_poll_interval_seconds,
                )
                if not health.ok:
                    return self._finish_failure(
                        run_id,
                        worktree,
                        health,
                        cwd,
                        server_info,
                        restart_history,
                        summary,
                        metrics,
                        ValidationResult(False, errors=["validation skipped"]),
                        "server_unhealthy",
                        "server health timeout",
                        run_results_dir,
                    )
                live.health = "ok"
                live.set_phase("cwd-check")
                cwd = client.verify_cwd(Path(worktree.path)) if self.options.cwd_check else CwdCheck(True, Path(worktree.path).as_posix(), cwd_check="skipped")
                live.cwd = cwd.cwd_check
                server_info = ServerInfo(
                    run_id=run_id,
                    pid=handle.pid,
                    hostname=HOSTNAME,
                    port=port,
                    base_url=base_url,
                    health_url=f"{base_url}/global/health",
                    requested_version=self.options.opencode_version,
                    reported_version=health.reported_version,
                    version_check=health.version_check,
                    expected_cwd=cwd.expected_cwd,
                    actual_cwd=cwd.actual_cwd,
                    cwd_check=cwd.cwd_check,
                    restart_count=restart_count,
                    server_start_elapsed_ms=int((time.monotonic() - server_start) * 1000),
                )
                metrics.server_start_elapsed_ms = server_info.server_start_elapsed_ms
                live.set_phase("server-info")
                self.emitter.emit({"type": "server_info", **dataclass_to_json(server_info)})
                mismatch_reason = None
                if health.version_check == "mismatch":
                    mismatch_reason = "version_mismatch"
                elif self.options.cwd_check and cwd.cwd_check != "ok":
                    mismatch_reason = "cwd_mismatch"
                if mismatch_reason is None:
                    break
                self.emitter.emit(
                    {
                        "type": "server_mismatch",
                        "run_id": run_id,
                        "reason": mismatch_reason,
                        "expected": self.options.opencode_version if mismatch_reason == "version_mismatch" else cwd.expected_cwd,
                        "actual": health.reported_version if mismatch_reason == "version_mismatch" else cwd.actual_cwd,
                    }
                )
                if not self.options.restart_on_mismatch or restart_count >= self.options.max_server_restarts:
                    failure: FailureClass = "server_restart_exhausted" if self.options.restart_on_mismatch else ("server_version_mismatch" if mismatch_reason == "version_mismatch" else "cwd_mismatch")
                    return self._finish_failure(
                        run_id,
                        worktree,
                        health,
                        cwd,
                        server_info,
                        restart_history,
                        summary,
                        metrics,
                        ValidationResult(False, errors=["validation skipped"]),
                        failure,
                        mismatch_reason,
                        run_results_dir,
                    )
                restart_count += 1
                metrics.server_restart_count = restart_count
                self.emitter.emit({"type": "server_restart", "run_id": run_id, "action": "stopping", "pid": handle.pid, "restart_count": restart_count})
                stop_result = self.process_manager.stop(handle)
                restart_history.append({"attempt": restart_count, "pid": handle.pid, "reason": mismatch_reason, **dataclass_to_json(server_info), **stop_result})
                client.close()
                self.emitter.emit({"type": "server_restart", "run_id": run_id, "action": "starting", "port": port, "restart_count": restart_count})
            live.set_phase("server-ready")
            metrics.server_ready = True
            live.set_phase("session-create")
            session_id = client.create_session(run_id, self.options.skill)
            live.set_phase("sse-connect")
            summary.sse_listener_started_at = now_iso()

            def on_event(event: SseEvent) -> None:
                record = event.to_record()
                record["type"] = "sse_event"
                record["run_id"] = run_id
                event_writer.write(record)
                summary.total_sse_events += 1
                if summary.first_event_at is None:
                    summary.first_event_at = now_iso()
                summary.last_event_at = now_iso()
                live.update_event(record)
                payload = record.get("json")
                if isinstance(payload, dict) and isinstance(payload.get("payload"), dict):
                    payload = payload["payload"]
                if isinstance(payload, dict):
                    update_metrics_from_event(metrics, payload)

            listener = SseListener(base_url, "/global/event", USERNAME, password, worktree.path, on_event)
            listener.start()
            sse_connected = listener.wait_connected(timeout=10.0) and listener.error is None
            summary.sse_connected_at = now_iso() if sse_connected else None
            gate_ok, gate_failures = prompt_gate(True, handle.alive(), health, server_info, cwd, session_id, sse_connected)
            if not gate_ok:
                return self._finish_failure(
                    run_id,
                    worktree,
                    health,
                    cwd,
                    server_info,
                    restart_history,
                    summary,
                    metrics,
                    ValidationResult(False, errors=["validation skipped"]),
                    "harness_error",
                    "; ".join(gate_failures),
                    run_results_dir,
                )
            live.set_phase("prompt-send")
            event_writer.write({"type": "prompt_request", "run_id": run_id, "session_id": session_id})
            client.send_prompt_async(session_id, self.options.prompt, self.options.skill, self.options.provider, self.options.model)
            summary.prompt_sent_at = now_iso()
            metrics.prompt_sent = True
            live.set_phase("running")
            last_activity = time.monotonic()
            status: dict[str, Any] = {}
            child_ids: list[str] = []
            deadline = time.monotonic() + self.options.hard_timeout_seconds
            while time.monotonic() < deadline:
                status = client.status()
                summary.total_status_polls += 1
                status_writer.write({"type": "status_snapshot", "run_id": run_id, "status": status, "at": now_iso()})
                children = client.children(session_id)
                summary.total_children_polls += 1
                children_writer.write({"type": "children_snapshot", "run_id": run_id, "children": children, "at": now_iso()})
                todo = client.todo(session_id)
                summary.total_todo_polls += 1
                todo_writer.write({"type": "todo_snapshot", "run_id": run_id, "todo": todo, "at": now_iso()})
                update_metrics_from_todo(metrics, todo)
                active = live.update_status(status)
                live.update_children(children)
                live.update_todo(todo)
                child_ids = [str(item.get("id")) for item in children if item.get("id")]
                if active:
                    last_activity = time.monotonic()
                live.quiet_seconds = time.monotonic() - last_activity
                self.emitter.emit({"type": "run_progress", **live.snapshot()})
                if idle_complete(status, [session_id, *child_ids], last_activity, self.options.idle_quiet_seconds):
                    break
                time.sleep(max(0.05, min(self.options.health_poll_interval_seconds, 1.0)))
            else:
                metrics.timeout = True
                return self._finish_failure(run_id, worktree, health, cwd, server_info, restart_history, summary, metrics, ValidationResult(False, errors=["validation skipped"]), "timeout", "hard timeout", run_results_dir)
            live.set_phase("idle-wait")
            diff = client.diff(session_id)
            (run_results_dir / "diff.patch").write_text(diff, encoding="utf-8")
            validation = validate_worktree(Path(worktree.path))
            write_json(run_results_dir / "validation.json", validation)
            apply_validation(metrics, validation)
            metrics.opencode_completed = True
            metrics.total_operational_ms = int((time.monotonic() - started_at) * 1000)
            metrics.idle_quiet_ms = int(self.options.idle_quiet_seconds * 1000)
            status_text = "completed" if validation.validation_passed else "failed"
            failure: FailureClass = "none" if validation.validation_passed else "validation_failure"
            summary.final_phase = status_text
            result = RunResult(run_id, self.batch, status_text, failure, worktree, health, cwd, server_info, restart_history, summary, metrics, validation)
            write_json(run_results_dir / "run.json", result)
            self.emitter.emit({"type": "run_completed" if status_text == "completed" else "run_failed", "run_id": run_id, "status": status_text, "failure_class": failure})
            return result
        except Exception as exc:
            validation = ValidationResult(False, errors=["validation skipped"])
            return self._finish_failure(run_id, locals().get("worktree"), health, cwd, server_info, restart_history, summary, metrics, validation, "harness_error", str(exc), run_results_dir)
        finally:
            if listener is not None:
                summary.sse_parser_errors = listener.parser.parse_errors
                listener.stop()
            if client is not None:
                client.close()
            if handle is not None:
                self.process_manager.stop(handle)
            for stream in (events_stream, status_stream, children_stream, todo_stream):
                stream.close()

    def _emit_worktree(self, run_id: str, path: Path) -> None:
        self.emitter.emit({"type": "worktree_created", "run_id": run_id, "path": str(path)})

    def _finish_failure(
        self,
        run_id: str,
        worktree: Any,
        health: HealthCheck | None,
        cwd: CwdCheck | None,
        server_info: ServerInfo | None,
        restart_history: list[dict[str, Any]],
        summary: LiveSummary,
        metrics: Metrics,
        validation: ValidationResult,
        failure_class: FailureClass,
        error_message: str,
        run_results_dir: Path,
    ) -> RunResult:
        metrics.harness_error = failure_class == "harness_error"
        metrics.total_operational_ms = metrics.total_operational_ms or 0
        summary.final_phase = "failed"
        write_json(run_results_dir / "validation.json", validation)
        result = RunResult(run_id, self.batch, "failed", failure_class, worktree, health, cwd, server_info, restart_history, summary, metrics, validation, error_message)
        write_json(run_results_dir / "run.json", result)
        self.emitter.emit({"type": "run_failed", "run_id": run_id, "status": "failed", "failure_class": failure_class, "reason": error_message})
        return result


def run_batch(
    options: BatchOptions,
    stream: TextIO,
    console_print: Callable[[str], None],
    process_manager: OpenCodeProcessManager | None = None,
    client_factory: Callable[[str, str, str, Path], OpenCodeClient] | None = None,
) -> tuple[Path, list[RunResult]]:
    options.repo = options.repo.resolve()
    options.output_dir = options.output_dir.resolve()
    options.output_dir.mkdir(parents=True, exist_ok=True)
    batch = batch_id()
    batch_dir = options.output_dir / batch
    batch_dir.mkdir(parents=True, exist_ok=True)
    base_commit = resolve_base_commit(options.repo, options.branch)
    emitter = ProgressEmitter(options.json, stream, console_print)
    executor = RunExecutor(options, batch, batch_dir, base_commit, emitter, process_manager, client_factory)
    results: list[RunResult] = []
    with ThreadPoolExecutor(max_workers=options.concurrency) as pool:
        futures = [pool.submit(executor.run, index) for index in range(1, options.count + 1)]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item.run_id)
    manifest = create_manifest(batch, options, base_commit)
    for result in results:
        run_entry = {
            "run_id": result.run_id,
            "status": result.status,
            "failure_class": result.failure_class,
            "worktree": dataclass_to_json(result.worktree),
            "temp_paths": [],
        }
        if result.worktree is not None:
            run_root = Path(result.worktree.path).parent
            run_entry["temp_paths"] = [str(run_root / "home"), str(run_root / "tmp"), str(run_root / "logs")]
        manifest["runs"].append(run_entry)
    write_json(batch_dir / "manifest.json", manifest)
    write_summary(batch_dir, results, options)
    return batch_dir, results
