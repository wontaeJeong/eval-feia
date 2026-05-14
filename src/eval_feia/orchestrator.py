from __future__ import annotations

import json
import subprocess
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, cast

from .live import LiveState, ProgressEmitter, RichLiveDisplay, todo_status, update_state_from_sse
from .metrics import compute_metrics
from .models import (
    CwdCheck,
    FailureClass,
    HealthCheck,
    LiveSummary,
    LOOPBACK_HOST,
    RunOptions,
    RunRecord,
    ServerInfo,
    WorktreeInfo,
    now_iso,
)
from .opencode_client import OpenCodeClient, build_prompt_payload, extract_cwd_value
from .process import ExternalServerProcessManager, OpenCodeProcessManager, ServerProcess
from .reports import JsonlWriter, write_json, write_summary
from .sse import SSEEvent, SSEListener
from .validation import validate_worktree
from .worktree import WorktreeManager, resolve_base_commit


class RunFailure(RuntimeError):
    def __init__(self, failure_class: str, message: str):
        super().__init__(message)
        self.failure_class = failure_class
        self.message = message


@dataclass
class BatchResult:
    batch_id: str
    batch_dir: Path
    manifest_path: Path
    records: list[RunRecord]

    @property
    def failed_count(self) -> int:
        return sum(1 for record in self.records if record.status != "completed")


@dataclass
class SessionGraphSnapshot:
    root_session_id: str
    child_session_ids: list[str]
    all_session_ids: list[str]
    non_idle_sessions: list[str]
    graph_signature: str
    all_idle: bool


class BatchRunner:
    def __init__(
        self,
        options: RunOptions,
        *,
        process_manager: Any | None = None,
        client_factory: Callable[[ServerProcess, Path], OpenCodeClient] | None = None,
        display: RichLiveDisplay | None = None,
    ):
        self.options = options
        self.repo = options.repo.resolve()
        self.batch_id = f"batch-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.batch_dir = (options.output_dir / self.batch_id).resolve()
        self.runs_dir = self.batch_dir / "runs"
        default_worktree_root = Path(tempfile.gettempdir()) / "eval-feia"
        self.worktree_batch_root = ((options.worktree_root or default_worktree_root) / self.batch_id).resolve()
        self.display = display
        self.emitter = ProgressEmitter(json_output=options.json_output, no_live=options.no_live, display=display)
        if process_manager is not None:
            self.process_manager = process_manager
        elif options.fake_server_url:
            self.process_manager = ExternalServerProcessManager(options.fake_server_url)
        else:
            self.process_manager = OpenCodeProcessManager()
        self.client_factory = client_factory or self._default_client_factory

    def run(self) -> BatchResult:
        self.batch_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        base_commit = resolve_base_commit(self.repo, self.options.branch)
        manifest: dict[str, Any] = {
            "batch_id": self.batch_id,
            "created_at": now_iso(),
            "repo": str(self.repo),
            "base_ref": self.options.branch,
            "base_commit": base_commit,
            "opencode_version": self.options.opencode_version,
            "runs": [],
        }
        write_json(self.batch_dir / "manifest.json", manifest)
        records: list[RunRecord] = []
        max_workers = max(1, self.options.concurrency)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(self._run_one, index, base_commit) for index in range(1, self.options.count + 1)]
            for future in as_completed(futures):
                records.append(future.result())
        records.sort(key=lambda record: record.run_id)
        manifest["runs"] = [self._manifest_run(record) for record in records]
        write_json(self.batch_dir / "manifest.json", manifest)
        write_summary(self.batch_dir, records, self.options.provider, self.options.model, self.options.opencode_version)
        return BatchResult(self.batch_id, self.batch_dir, self.batch_dir / "manifest.json", records)

    def _run_one(self, index: int, base_commit: str) -> RunRecord:
        run_id = f"run-{index:03d}"
        port = self.options.base_port + index - 1
        run_dir = self.runs_dir / run_id
        run_temp_dir = self.worktree_batch_root / run_id
        run_home = run_temp_dir / "home"
        run_tmp = run_temp_dir / "tmp"
        run_log_dir = run_temp_dir / "logs"
        run_artifacts = run_dir / "artifacts"
        run_dir.mkdir(parents=True, exist_ok=True)
        run_artifacts.mkdir(parents=True, exist_ok=True)
        (run_dir / "prompt.txt").write_text(self.options.prompt, encoding="utf-8")
        events_writer = JsonlWriter(run_dir / "events.jsonl")
        status_writer = JsonlWriter(run_dir / "status_snapshots.jsonl")
        children_writer = JsonlWriter(run_dir / "children_snapshots.jsonl")
        todo_writer = JsonlWriter(run_dir / "todo_snapshots.jsonl")
        record = RunRecord(run_id=run_id, batch_id=self.batch_id, live_summary=LiveSummary())
        state = LiveState(run_id=run_id, port=port)
        self._set_phase(state, "worktree")
        process: ServerProcess | None = None
        prompt_sent = False
        operational_start = time.monotonic()
        server_start_elapsed_ms = -1
        idle_quiet_ms = 0
        try:
            worktree_info = WorktreeManager(self.repo, self.options.branch, base_commit).create(
                run_id, run_temp_dir, emit=self.emitter.emit
            )
            record.worktree = worktree_info
            state.worktree_path = str(worktree_info.path)
            process, client, server_info, health, cwd, restart_history = self._start_ready_server(
                run_id=run_id,
                port=port,
                run_home=run_home,
                run_tmp=run_tmp,
                run_log_dir=run_log_dir,
                worktree=worktree_info,
                state=state,
                events_writer=events_writer,
            )
            server_start_elapsed_ms = server_info.server_start_elapsed_ms
            record.server_info = server_info
            record.server_health = health
            record.cwd_check = cwd
            record.server_restart_history = restart_history
            self._set_phase(state, "session-create")
            session = client.create_session(title=f"eval-feia {run_id}")
            session_id = _session_id(session)
            if not session_id:
                raise RunFailure(FailureClass.HARNESS_ERROR, "OpenCode session response did not include an id")
            self._set_phase(state, "sse-connect")
            listener = SSEListener(
                run_id=run_id,
                client=client,
                endpoint="/event",
                events_writer=events_writer,
                live_summary=record.live_summary,
                on_event=lambda event: self._on_sse_event(state, event),
            )
            listener.start()
            if not listener.wait_connected(timeout=max(2.0, self.options.server_start_timeout_seconds)):
                raise RunFailure(FailureClass.HARNESS_ERROR, "SSE listener did not connect before prompt")
            if not process.is_alive() or server_info.version_check == "mismatch" or server_info.cwd_check == "mismatch":
                raise RunFailure(FailureClass.HARNESS_ERROR, "Prompt gate failed")
            self._set_phase(state, "prompt-send")
            payload = build_prompt_payload(
                self.options.prompt,
                provider=self.options.provider,
                model=self.options.model,
                agent=self.options.skill,
            )
            events_writer.write({"type": "prompt_request", "run_id": run_id, "session_id": session_id, "agent": self.options.skill})
            client.send_prompt_async(session_id, payload)
            prompt_sent = True
            record.live_summary.prompt_sent_at = now_iso()
            self._set_phase(state, "running")
            idle_quiet_ms = self._monitor_until_idle(
                run_id=run_id,
                client=client,
                session_id=session_id,
                state=state,
                listener=listener,
                status_writer=status_writer,
                children_writer=children_writer,
                todo_writer=todo_writer,
                live_summary=record.live_summary,
            )
            listener.stop()
            agent_done = True
            artifact_done = self._collect_diff(client, session_id, run_dir, worktree_info.path)
            validation = validate_worktree(worktree_info.path, run_dir / "validation.json")
            record.validation = validation
            test_done = validation.validation_passed
            total_ms = int((time.monotonic() - operational_start) * 1000)
            record.metrics = compute_metrics(
                run_dir=run_dir,
                state=state,
                validation=validation,
                restart_count=server_info.restart_count,
                server_start_elapsed_ms=server_start_elapsed_ms,
                total_operational_ms=total_ms,
                idle_quiet_ms=idle_quiet_ms,
                prompt_sent=prompt_sent,
                completed=agent_done and test_done and artifact_done,
                timeout=False,
                harness_error=False,
            )
            if agent_done and test_done and artifact_done:
                record.status = "completed"
                record.failure_class = FailureClass.NONE
                self._set_phase(state, "completed")
                self.emitter.emit({"type": "run_completed", "run_id": run_id, "status": "completed"})
            else:
                record.status = "failed"
                record.failure_class = FailureClass.VALIDATION_FAILURE if not test_done else FailureClass.AGENT_FAILURE
                record.error_message = "; ".join(validation.errors) if not test_done else "artifact collection incomplete"
                self._set_phase(state, "failed", record.error_message)
                self.emitter.emit({"type": "run_failed", "run_id": run_id, "failure_class": record.failure_class})
        except RunFailure as exc:
            record.status = "failed"
            record.failure_class = exc.failure_class
            record.error_message = exc.message
            self._set_phase(state, "failed", exc.message)
            validation = validate_worktree(record.worktree.path, run_dir / "validation.json") if record.worktree else record.validation
            record.validation = validation
            total_ms = int((time.monotonic() - operational_start) * 1000)
            record.metrics = compute_metrics(
                run_dir=run_dir,
                state=state,
                validation=record.validation,
                restart_count=record.server_info.restart_count if record.server_info else len(record.server_restart_history),
                server_start_elapsed_ms=server_start_elapsed_ms,
                total_operational_ms=total_ms,
                idle_quiet_ms=idle_quiet_ms,
                prompt_sent=prompt_sent,
                completed=False,
                timeout=exc.failure_class == FailureClass.TIMEOUT,
                harness_error=exc.failure_class == FailureClass.HARNESS_ERROR,
            )
            self.emitter.emit({"type": "run_failed", "run_id": run_id, "failure_class": record.failure_class, "error": exc.message})
        except Exception as exc:
            record.status = "failed"
            record.failure_class = FailureClass.HARNESS_ERROR
            record.error_message = str(exc)
            self._set_phase(state, "failed", str(exc))
            total_ms = int((time.monotonic() - operational_start) * 1000)
            record.metrics = compute_metrics(
                run_dir=run_dir,
                state=state,
                validation=record.validation,
                restart_count=record.server_info.restart_count if record.server_info else len(record.server_restart_history),
                server_start_elapsed_ms=server_start_elapsed_ms,
                total_operational_ms=total_ms,
                idle_quiet_ms=idle_quiet_ms,
                prompt_sent=prompt_sent,
                completed=False,
                timeout=False,
                harness_error=True,
            )
            self.emitter.emit({"type": "run_failed", "run_id": run_id, "failure_class": record.failure_class, "error": str(exc)})
        finally:
            if process is not None:
                process.stop(grace_seconds=1.0)
            record.completed_at = now_iso()
            record.live_summary.renderer_refresh_count = self.display.refresh_count if self.display else 0
            record.live_summary.final_phase = state.phase
            write_json(run_dir / "run.json", record)
            events_writer.close()
            status_writer.close()
            children_writer.close()
            todo_writer.close()
        return record

    def _start_ready_server(
        self,
        *,
        run_id: str,
        port: int,
        run_home: Path,
        run_tmp: Path,
        run_log_dir: Path,
        worktree: WorktreeInfo,
        state: LiveState,
        events_writer: JsonlWriter,
    ) -> tuple[ServerProcess, OpenCodeClient, ServerInfo, HealthCheck, CwdCheck, list[dict[str, Any]]]:
        restart_count = 0
        restart_history: list[dict[str, Any]] = []
        while True:
            self._set_phase(state, "server-starting")
            if restart_count:
                self.emitter.emit({"type": "server_restart", "run_id": run_id, "action": "starting", "port": port, "restart_count": restart_count})
            started = time.monotonic()
            process = cast(ServerProcess, self.process_manager.start(
                cwd=worktree.path,
                run_home=run_home,
                run_tmp=run_tmp,
                port=port,
                version=self.options.opencode_version,
                log_path=run_log_dir / "opencode.log",
                hostname=LOOPBACK_HOST,
            ))
            client = self.client_factory(process, worktree.path)
            health = self._wait_for_health(client, process, state)
            server_elapsed_ms = int((time.monotonic() - started) * 1000)
            reported_version = health.version
            version_check = "unknown" if not reported_version else ("match" if reported_version == self.options.opencode_version else "mismatch")
            cwd = self._check_cwd(client, worktree.path, state)
            if version_check == "mismatch" or cwd.result == "mismatch":
                reason = "version_mismatch" if version_check == "mismatch" else "cwd_mismatch"
                expected = self.options.opencode_version if reason == "version_mismatch" else str(worktree.path)
                actual = reported_version if reason == "version_mismatch" else cwd.actual_cwd
                self._set_phase(state, "server-mismatch", reason)
                self.emitter.emit({"type": "server_mismatch", "run_id": run_id, "reason": reason, "expected": expected, "actual": actual})
                events_writer.write({"type": "server_mismatch", "run_id": run_id, "reason": reason})
                termination = process.stop(grace_seconds=1.0)
                restart_history.append(
                    {
                        "attempt": restart_count + 1,
                        "pid": process.pid,
                        "reason": reason,
                        "requested_version": self.options.opencode_version,
                        "reported_version": reported_version,
                        "expected_cwd": str(worktree.path),
                        "actual_cwd": cwd.actual_cwd,
                        "terminated": termination.terminated,
                        "killed": termination.killed,
                        "elapsed_ms": termination.elapsed_ms,
                    }
                )
                if not self.options.restart_on_mismatch:
                    failure = FailureClass.SERVER_VERSION_MISMATCH if reason == "version_mismatch" else FailureClass.CWD_MISMATCH
                    raise RunFailure(failure, f"{reason} and restart disabled")
                if restart_count >= self.options.max_server_restarts:
                    self._set_phase(state, "server-restart-exhausted", reason)
                    raise RunFailure(FailureClass.SERVER_RESTART_EXHAUSTED, f"restart exhausted after {reason}")
                restart_count += 1
                state.restart_count = restart_count
                self.emitter.emit({"type": "server_restart", "run_id": run_id, "action": "stopping", "pid": process.pid, "restart_count": restart_count})
                continue
            server_info = ServerInfo(
                run_id=run_id,
                pid=process.pid,
                hostname=LOOPBACK_HOST,
                port=port,
                base_url=process.base_url,
                health_url=f"{process.base_url}/global/health",
                requested_version=self.options.opencode_version,
                reported_version=reported_version,
                version_check=version_check,
                expected_cwd=str(worktree.path),
                actual_cwd=cwd.actual_cwd,
                cwd_check=cwd.result,
                restart_count=restart_count,
                server_start_elapsed_ms=server_elapsed_ms,
            )
            self._set_phase(state, "server-info")
            info_event = {
                "type": "server_info",
                "run_id": run_id,
                "pid": process.pid,
                "hostname": LOOPBACK_HOST,
                "port": port,
                "base_url": process.base_url,
                "requested_version": self.options.opencode_version,
                "reported_version": reported_version,
                "version_check": version_check,
                "expected_cwd": str(worktree.path),
                "actual_cwd": cwd.actual_cwd,
                "cwd_check": cwd.result,
                "restart_count": restart_count,
            }
            self.emitter.emit(info_event)
            events_writer.write(info_event)
            self._set_phase(state, "server-ready")
            return process, client, server_info, health, cwd, restart_history

    def _wait_for_health(self, client: OpenCodeClient, process: ServerProcess, state: LiveState) -> HealthCheck:
        self._set_phase(state, "server-health")
        started = time.monotonic()
        last_error: str | None = None
        while time.monotonic() - started < self.options.server_start_timeout_seconds:
            if not process.is_alive():
                raise RunFailure(FailureClass.SERVER_UNHEALTHY, "OpenCode server process exited before health check")
            try:
                raw = client.get_health()
                healthy = bool(raw.get("healthy"))
                version = raw.get("version") if isinstance(raw.get("version"), str) else None
                elapsed_ms = int((time.monotonic() - started) * 1000)
                if healthy:
                    state.health = "ok"
                    return HealthCheck(ok=True, healthy=True, version=version, elapsed_ms=elapsed_ms, raw=raw)
                last_error = "health response was not healthy"
            except Exception as exc:
                last_error = str(exc)
            time.sleep(self.options.health_poll_interval_seconds)
        state.health = "fail"
        raise RunFailure(FailureClass.SERVER_UNHEALTHY, last_error or "OpenCode health check timed out")

    def _check_cwd(self, client: OpenCodeClient, expected: Path, state: LiveState) -> CwdCheck:
        self._set_phase(state, "cwd-check")
        if not self.options.cwd_check:
            state.cwd = "skip"
            return CwdCheck(expected_cwd=str(expected), result="skipped")
        raw: dict[str, Any] = {}
        actual: str | None = None
        source = "/path"
        try:
            raw = client.get_path()
            actual = extract_cwd_value(raw)
            if actual is None:
                source = "/project/current"
                raw = client.get_project_current()
                actual = extract_cwd_value(raw)
            if actual is None:
                state.cwd = "unknown"
                return CwdCheck(expected_cwd=str(expected), actual_cwd=None, result="mismatch", source=source, raw=raw)
            result = "ok" if Path(actual).resolve() == expected.resolve() else "mismatch"
            state.cwd = result
            return CwdCheck(expected_cwd=str(expected), actual_cwd=str(Path(actual).resolve()), result=result, source=source, raw=raw)
        except Exception as exc:
            state.cwd = "error"
            return CwdCheck(expected_cwd=str(expected), actual_cwd=actual, result="mismatch", source=source, raw=raw, error=str(exc))

    def _monitor_until_idle(
        self,
        *,
        run_id: str,
        client: OpenCodeClient,
        session_id: str,
        state: LiveState,
        listener: SSEListener,
        status_writer: JsonlWriter,
        children_writer: JsonlWriter,
        todo_writer: JsonlWriter,
        live_summary: LiveSummary,
    ) -> int:
        started = time.monotonic()
        stable_idle_polls = 0
        required_stable_polls = 3
        previous_signature = ""
        while True:
            elapsed = time.monotonic() - started
            if elapsed > self.options.hard_timeout_seconds:
                self._set_phase(state, "timeout")
                graph = self._poll_session_graph(client, session_id)
                raise RunFailure(
                    FailureClass.TIMEOUT,
                    "run hard timeout exceeded "
                    f"root_session_id={session_id} "
                    f"child_session_ids={graph.child_session_ids} "
                    f"non_idle_sessions={graph.non_idle_sessions} "
                    f"elapsed_time={int(elapsed)}s",
                )
            status = client.get_session_status()
            graph = self._poll_session_graph(client, session_id, status=status)
            todos = client.get_session_todo(session_id)
            live_summary.total_status_polls += 1
            live_summary.total_children_polls += 1
            live_summary.total_todo_polls += 1
            status_writer.write({"type": "status_snapshot", "run_id": run_id, "status": status})
            children_writer.write(
                {
                    "type": "children_snapshot",
                    "run_id": run_id,
                    "root_session_id": session_id,
                    "items": graph.child_session_ids,
                    "all_session_ids": graph.all_session_ids,
                    "non_idle_sessions": graph.non_idle_sessions,
                }
            )
            todo_writer.write({"type": "todo_snapshot", "run_id": run_id, "items": todos})
            state.child_session_count = max(state.child_session_count, len(graph.child_session_ids))
            state.todo_status = todo_status(todos)
            busy = (not graph.all_idle) or _todo_busy(todos)
            if graph.graph_signature != previous_signature:
                stable_idle_polls = 0
                previous_signature = graph.graph_signature
            elif not busy:
                stable_idle_polls += 1
            else:
                stable_idle_polls = 0
            quiet = float(stable_idle_polls)
            state.quiet_seconds = quiet
            self._set_phase(state, "running" if busy else "idle-wait")
            if not busy and stable_idle_polls >= required_stable_polls:
                return stable_idle_polls * int(self.options.health_poll_interval_seconds * 1000)
            time.sleep(min(0.5, max(0.05, self.options.health_poll_interval_seconds)))

    def _poll_session_graph(
        self, client: OpenCodeClient, root_session_id: str, *, status: dict[str, Any] | None = None
    ) -> SessionGraphSnapshot:
        status_map = status if status is not None else client.get_session_status()
        descendants: set[str] = set()
        queue = [root_session_id]
        while queue:
            current = queue.pop(0)
            for child in client.get_session_children(current):
                child_id = _session_id(child) or str(child.get("id", ""))
                if not child_id or child_id in descendants:
                    continue
                descendants.add(child_id)
                queue.append(child_id)
        all_ids = [root_session_id, *sorted(descendants)]
        non_idle = [sid for sid in all_ids if _session_state_busy(status_map, sid)]
        signature = json.dumps({"sessions": all_ids, "non_idle": non_idle}, ensure_ascii=False, sort_keys=True)
        return SessionGraphSnapshot(
            root_session_id=root_session_id,
            child_session_ids=sorted(descendants),
            all_session_ids=all_ids,
            non_idle_sessions=non_idle,
            graph_signature=signature,
            all_idle=len(non_idle) == 0,
        )

    def _collect_diff(self, client: OpenCodeClient, session_id: str, run_dir: Path, worktree: Path) -> bool:
        diff_path = run_dir / "diff.patch"
        try:
            diff = client.get_diff(session_id)
            if isinstance(diff, str):
                diff_path.write_text(diff, encoding="utf-8")
            else:
                diff_path.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
        except Exception:
            pass
        result = subprocess.run(["git", "-C", str(worktree), "diff"], check=False, capture_output=True, text=True)
        diff_path.write_text(result.stdout, encoding="utf-8")
        return result.returncode == 0

    def _on_sse_event(self, state: LiveState, event: SSEEvent) -> None:
        update_state_from_sse(state, event.type)

    def _set_phase(self, state: LiveState, phase: str, note: str = "") -> None:
        state.phase = phase
        if note:
            state.note = note
        self.emitter.state(state)
        if self.options.json_output:
            self.emitter.emit(
                {
                    "type": "run_progress",
                    "run_id": state.run_id,
                    "phase": state.phase,
                    "msg": state.message_count,
                    "tool": state.tool_call_count,
                    "child": state.child_session_count,
                    "todo": state.todo_status,
                    "quiet": int(state.quiet_seconds),
                    "elapsed_ms": int((time.monotonic() - state.started_monotonic) * 1000),
                }
            )

    def _manifest_run(self, record: RunRecord) -> dict[str, Any]:
        run_dir = self.runs_dir / record.run_id
        temp_dir = self.worktree_batch_root / record.run_id
        return {
            "run_id": record.run_id,
            "status": record.status,
            "failure_class": record.failure_class,
            "run_dir": str(run_dir),
            "temp_dir": str(temp_dir),
            "worktree": record.worktree,
            "server_info": record.server_info,
        }

    def _default_client_factory(self, process: ServerProcess, directory: Path) -> OpenCodeClient:
        return OpenCodeClient(process.base_url, username=process.username, password=process.password, directory=directory)


def _session_id(session: dict[str, Any]) -> str | None:
    for key in ("id", "ID", "sessionID", "session_id"):
        value = session.get(key)
        if isinstance(value, str):
            return value
    nested = session.get("session")
    if isinstance(nested, dict):
        return _session_id(nested)
    return None


def _status_busy(status: Any) -> bool:
    text = json.dumps(status, ensure_ascii=False).lower() if not isinstance(status, str) else status.lower()
    busy_words = ("running", "busy", "working", "streaming", "in_progress", "queued")
    idle_words = ("idle", "completed", "done")
    return any(word in text for word in busy_words) and not any(word in text for word in idle_words)


def _todo_busy(todos: list[dict[str, Any]]) -> bool:
    return any(str(item.get("status", "")).lower() in {"pending", "in_progress", "running"} for item in todos)


def _session_state_busy(status_payload: Any, session_id: str) -> bool:
    if not isinstance(status_payload, dict):
        return False
    raw = status_payload.get(session_id)
    if raw is None:
        return False
    if isinstance(raw, dict):
        state = str(raw.get("status", "")).lower()
    else:
        state = str(raw).lower()
    return state not in {"idle", "completed", "done"}


def run_batch(options: RunOptions, *, display: RichLiveDisplay | None = None) -> BatchResult:
    return BatchRunner(options, display=display).run()
