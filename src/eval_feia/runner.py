from __future__ import annotations

import concurrent.futures
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
from rich.console import Console

from .collector import collect_candidate
from .config import EvalConfig, EvalItemConfig, read_prompt
from .errors import ErrorRecord, EvalFeiaError, HealthError
from .git_worktree import (
    GitWorktreeManager,
    LocalGitArtifacts,
    append_branch_suffix,
    branch_name_to_path_slug,
    sanitize_branch_name,
    sanitize_path_slug,
)
from .manifest import (
    CandidateManifestRecord,
    Manifest,
    RepoRecord,
    ServerRecord,
    utc_now_iso,
    write_json,
    write_manifest,
)
from .opencode_client import OpencodeClient, normalize_command
from .summary import parse_numstat, print_summary, write_run_summary


@dataclass(slots=True)
class RunOutcome:
    run_id: str
    output_dir: Path
    summary: dict[str, Any]
    passed: bool


@dataclass(slots=True)
class CandidateSpec:
    id: str
    eval_id: str
    index: int
    total: int
    label: str
    requested_branch_name: str | None
    branch_name: str
    prompt: str


def generate_run_id() -> str:
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"


def run_evaluation(
    config: EvalConfig,
    *,
    console: Console | None = None,
    client: OpencodeClient | None = None,
    run_id: str | None = None,
) -> RunOutcome:
    active_console = console if console is not None else Console()
    actual_run_id = run_id or generate_run_id()
    specs = _build_candidate_specs(config, actual_run_id)
    manager = GitWorktreeManager(config.repo.path)
    repo_root = manager.ensure_repo()
    base_sha = manager.resolve_sha(config.repo.base_ref)

    owns_client = client is None
    if client is None:
        client = OpencodeClient(
            config.server.url,
            username=config.server.username,
            password=config.server.password(),
            timeout=30.0,
        )

    try:
        health = _health_with_retry(client, config)
        version = str(health.get("version") or "unknown")

        output_dir = (config.run.output_root / actual_run_id).resolve(strict=False)
        worktree_root = (config.repo.worktree_root / actual_run_id).resolve(strict=False)
        output_dir.mkdir(parents=True, exist_ok=False)
        (output_dir / "candidates").mkdir(parents=True, exist_ok=True)

        _print_run_context(
            active_console,
            config,
            run_id=actual_run_id,
            repo_root=repo_root,
            base_sha=base_sha,
            version=version,
            output_dir=output_dir,
            worktree_root=worktree_root,
            candidate_count=len(specs),
        )

        manifest = Manifest(
            run_id=actual_run_id,
            created_at=utc_now_iso(),
            repo=RepoRecord(path=repo_root, base_ref=config.repo.base_ref, base_sha=base_sha),
            server=ServerRecord(url=config.server.url, version=version),
            output_dir=output_dir,
            worktree_root=worktree_root,
            candidates=[],
        )
        write_manifest(manifest)

        records = _create_worktrees(config, specs, manager, manifest, active_console)
        candidate_results = _execute_candidates(
            config,
            specs,
            client,
            manager,
            manifest,
            records,
            active_console,
        )
        summary = write_run_summary(manifest, candidate_results, health=health)
        print_summary(active_console, summary)
        return RunOutcome(actual_run_id, output_dir, summary, bool(summary["passed"]))
    finally:
        if owns_client:
            client.close()


def _health_with_retry(client: OpencodeClient, config: EvalConfig) -> dict[str, Any]:
    last_error = ""
    for attempt in range(1, config.server.health_retries + 1):
        try:
            health = client.health(timeout=config.server.health_timeout_seconds)
            if health.get("healthy", True) is False:
                last_error = f"server reported unhealthy: {health}"
            else:
                return health
        except Exception as exc:
            last_error = str(exc)
        if attempt < config.server.health_retries:
            time.sleep(config.server.health_interval_ms / 1000)
    raise HealthError(
        "opencode server health check failed; start it with "
        "`opencode serve --hostname 127.0.0.1 --port 4096`",
        details={
            "server_url": config.server.url,
            "attempts": config.server.health_retries,
            "last_error": last_error,
        },
    )


def _build_candidate_specs(config: EvalConfig, run_id: str | None = None) -> list[CandidateSpec]:
    has_explicit_evals = bool(config.evals)
    items = config.evals or [EvalItemConfig() for _ in range(1, config.run.candidates + 1)]
    total = len(items)
    used_ids: set[str] = set()
    used_branch_names: set[str] = set()
    specs: list[CandidateSpec] = []
    for index, item in enumerate(items, start=1):
        default_id = f"cand-{index:03d}"
        explicit_eval_id = _non_empty(item.id)
        candidate_id = _unique_candidate_id(explicit_eval_id or default_id, used_ids)
        eval_id = explicit_eval_id or candidate_id
        label = _resolved_label(item, config, explicit_eval_id, default_id, has_explicit_evals)
        requested_branch_name = item.branch_name
        fallback_source = explicit_eval_id or candidate_id
        branch_name = _unique_branch_name(
            _candidate_branch_name(run_id, requested_branch_name, fallback_source),
            used_branch_names,
        )
        specs.append(
            CandidateSpec(
                id=candidate_id,
                eval_id=eval_id,
                index=index,
                total=total,
                label=label,
                requested_branch_name=requested_branch_name,
                branch_name=branch_name,
                prompt=_prompt_for_eval(config, item),
            )
        )
    return specs


def _candidate_branch_name(
    run_id: str | None,
    requested_branch_name: str | None,
    fallback_source: str,
) -> str:
    if run_id is None:
        return sanitize_branch_name(requested_branch_name, f"eval/{fallback_source}")
    run_slug = sanitize_path_slug(run_id, fallback="run")
    source = requested_branch_name or fallback_source
    source_leaf = branch_name_to_path_slug(_branch_source_without_default_namespace(source))
    return sanitize_branch_name(None, f"eval/{run_slug}/{source_leaf}")


def _unique_branch_name(branch_name: str, used_branch_names: set[str]) -> str:
    candidate = branch_name
    suffix = 2
    while candidate in used_branch_names:
        candidate = append_branch_suffix(branch_name, suffix)
        suffix += 1
    used_branch_names.add(candidate)
    return candidate


def _branch_source_without_default_namespace(value: str) -> str:
    branch = sanitize_branch_name(value, "candidate")
    if branch.startswith("eval/"):
        branch = branch[len("eval/") :]
    return branch


def _resolved_label(
    item: EvalItemConfig,
    config: EvalConfig,
    explicit_eval_id: str | None,
    default_id: str,
    has_explicit_evals: bool,
) -> str:
    label = _non_empty(item.label)
    if label is not None:
        return label
    if explicit_eval_id is not None:
        return explicit_eval_id
    run_label = _non_empty(config.run.label)
    if run_label is not None and not has_explicit_evals:
        return run_label
    return default_id


def _prompt_for_eval(config: EvalConfig, item: EvalItemConfig) -> str:
    if item.prompt is not None or item.prompt_file is not None:
        return read_prompt(item.prompt, item.prompt_file)
    if config.run.prompt is not None or config.run.prompt_file is not None:
        return read_prompt(config.run.prompt, config.run.prompt_file)
    raise EvalFeiaError("config_error", "no prompt or prompt_file configured")


def _unique_candidate_id(value: str, used_ids: set[str]) -> str:
    base = sanitize_path_slug(value, fallback="cand")
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _create_worktrees(
    config: EvalConfig,
    specs: list[CandidateSpec],
    manager: GitWorktreeManager,
    manifest: Manifest,
    console: Console,
) -> list[CandidateManifestRecord]:
    records: list[CandidateManifestRecord] = []
    for spec in specs:
        result_dir = manifest.output_dir / "candidates" / spec.id
        result_dir.mkdir(parents=True, exist_ok=True)
        created = manager.create_branch_worktree(
            manifest.worktree_root,
            _worktree_path_slug(spec.id),
            config.repo.base_ref,
            spec.branch_name,
        )
        prefix = f"[{spec.index}/{spec.total}]"
        console.print(f"{prefix} candidate: {spec.id}", markup=False)
        console.print(f"{prefix} eval: {spec.eval_id}", markup=False)
        console.print(f"{prefix} label: {spec.label}", markup=False)
        if (
            spec.requested_branch_name is not None
            and spec.requested_branch_name != created.branch_name
        ):
            console.print(f"{prefix} requested branch: {spec.requested_branch_name}", markup=False)
            console.print(f"{prefix} resolved branch: {created.branch_name}", markup=False)
        else:
            console.print(f"{prefix} branch: {created.branch_name}", markup=False)
        console.print(f"{prefix} worktree: {created.path}", markup=False)
        record = CandidateManifestRecord(
            id=spec.id,
            eval_id=spec.eval_id,
            label=spec.label,
            requested_branch_name=spec.requested_branch_name,
            branch_name=created.branch_name,
            worktree_path=created.path,
            result_dir=result_dir.resolve(strict=False),
            status="created",
        )
        manifest.upsert_candidate(record)
        write_manifest(manifest)
        records.append(record)
    return records


def _execute_candidates(
    config: EvalConfig,
    specs: list[CandidateSpec],
    client: OpencodeClient,
    manager: GitWorktreeManager,
    manifest: Manifest,
    records: list[CandidateManifestRecord],
    console: Console,
) -> list[dict[str, Any]]:
    lock = threading.Lock()
    results: list[dict[str, Any]] = []
    specs_by_id = {spec.id: spec for spec in specs}

    def run_one(record: CandidateManifestRecord) -> dict[str, Any]:
        result = _execute_candidate(
            config,
            specs_by_id[record.id].prompt,
            client,
            manager,
            manifest,
            record,
            console,
            lock,
        )
        with lock:
            results.append(result)
        return result

    if config.run.concurrency <= 1 or len(records) <= 1:
        return [run_one(record) for record in records]

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.run.concurrency) as executor:
        future_map = {executor.submit(run_one, record): record for record in records}
        ordered: dict[str, dict[str, Any]] = {}
        for future in concurrent.futures.as_completed(future_map):
            record = future_map[future]
            ordered[record.id] = future.result()
        return [ordered[record.id] for record in records]


def _execute_candidate(
    config: EvalConfig,
    prompt: str,
    client: OpencodeClient,
    manager: GitWorktreeManager,
    manifest: Manifest,
    record: CandidateManifestRecord,
    console: Console,
    lock: threading.Lock,
) -> dict[str, Any]:
    started = time.monotonic()
    started_at = utc_now_iso()
    error: ErrorRecord | None = None
    session_id: str | None = None
    collection_errors: list[ErrorRecord] = []
    validation = {"commands": [], "passed": True}
    stats = {"files_changed": 0, "additions": 0, "deletions": 0}
    result_dir = record.result_dir
    worktree = record.worktree_path
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "worktree.txt").write_text(f"{worktree}\n", encoding="utf-8")

    try:
        client.path(worktree)
        _best_effort_preflight(client, worktree)
        session = client.session_create(worktree, f"eval-feia/{manifest.run_id}/{record.id}")
        session_id = _session_id(session)
        _validate_session_directory(session, worktree)
        _update_manifest(manifest, record, session_id=session_id, status="running", lock=lock)
        console.print(f"{_record_prefix(record)} session: {session_id}", markup=False)
        client.session_prompt(
            worktree,
            session_id,
            prompt,
            command=config.run.command,
            agent=config.run.agent,
            model=_model_dict(config.run.model),
            timeout=config.run.timeout_seconds,
        )
        collection = collect_candidate(client, worktree, session_id, result_dir)
        collection_errors = collection.errors
        local = manager.collect_local_artifacts(worktree)
        _write_local_artifacts(result_dir, local)
        validation = _run_validation(config, worktree, result_dir)
        stats = parse_numstat(local.diff_numstat)
        stats["files_changed"] = max(stats["files_changed"], _count_status_files(local.status_short))
        if collection_errors:
            error = collection_errors[0]
        elif not validation["passed"]:
            error = ErrorRecord("validation_failed", "one or more required validation commands failed")
    except httpx.TimeoutException as exc:
        error = ErrorRecord(
            "timeout",
            f"candidate exceeded timeout_seconds={config.run.timeout_seconds:g}",
            recoverable=True,
            details={"exception": str(exc)},
        )
        if session_id:
            _abort_after_timeout(client, worktree, session_id, error)
            collection = collect_candidate(client, worktree, session_id, result_dir)
            collection_errors = collection.errors
            _collect_local_best_effort(manager, worktree, result_dir)
    except EvalFeiaError as exc:
        error = exc.record
        if session_id:
            collection = collect_candidate(client, worktree, session_id, result_dir)
            collection_errors = collection.errors
            _collect_local_best_effort(manager, worktree, result_dir)
    except httpx.HTTPStatusError as exc:
        error = ErrorRecord(
            "prompt_failed" if session_id else "session_create_failed",
            f"opencode returned HTTP {exc.response.status_code}",
            details={"response_body": exc.response.text},
        )
        if session_id:
            collection = collect_candidate(client, worktree, session_id, result_dir)
            collection_errors = collection.errors
            _collect_local_best_effort(manager, worktree, result_dir)
    except Exception as exc:
        error = ErrorRecord("unexpected_error", str(exc), details={"type": type(exc).__name__})
        if session_id:
            collection = collect_candidate(client, worktree, session_id, result_dir)
            collection_errors = collection.errors
            _collect_local_best_effort(manager, worktree, result_dir)

    completed_at = utc_now_iso()
    status = "passed" if error is None else "failed"
    validation_status = "passed" if validation.get("passed") else "failed"
    candidate_result = {
        "candidate_id": record.id,
        "eval_id": record.eval_id or record.id,
        "label": record.label or record.eval_id or record.id,
        "base_ref": manifest.repo.base_ref,
        "base_sha": manifest.repo.base_sha,
        "requested_branch_name": record.requested_branch_name,
        "branch_name": record.branch_name,
        "status": status,
        "worktree_path": str(worktree),
        "session_id": session_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": round(time.monotonic() - started, 3),
        "validation_status": validation_status,
        "opencode": {
            "session": "session.json",
            "messages": "messages.json",
            "children": "children.json",
            "todo": "todo.json",
            "diff": "diff.json",
            "file_status": "file-status.json",
        },
        "local": {
            "git_status": "git-status.txt",
            "git_diff": "local-git-diff.patch",
            "validation": "validation.json",
        },
        "summary": {**stats, "final_output_file": "final-output.md"},
        "collection_errors": [item.to_dict() for item in collection_errors],
        "error": error.to_dict() if error else None,
    }
    write_json(result_dir / "validation.json", validation)
    if error:
        write_json(result_dir / "error.json", error.to_dict())
    write_json(result_dir / "result.json", candidate_result)
    _update_manifest(manifest, record, session_id=session_id, status=status, lock=lock)
    console.print(
        f"{_record_prefix(record)} status: {status}; validation: {validation_status}",
        markup=False,
    )
    return candidate_result


def _best_effort_preflight(client: OpencodeClient, worktree: Path) -> None:
    for call in (client.project_current, client.config, client.vcs):
        try:
            call(worktree)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {404, 405, 501}:
                raise
        except httpx.HTTPError:
            raise


def _session_id(session: dict[str, Any]) -> str:
    session_id = session.get("id") or session.get("sessionID") or session.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise EvalFeiaError("session_create_failed", "opencode session response did not include an id")
    return session_id


def _validate_session_directory(session: dict[str, Any], expected: Path) -> None:
    returned = session.get("directory") or session.get("path")
    if not returned:
        return
    returned_path = Path(unquote(str(returned))).expanduser().resolve(strict=False)
    expected_path = expected.expanduser().resolve(strict=False)
    if returned_path != expected_path:
        raise EvalFeiaError(
            "directory_context_mismatch",
            "opencode created the session in a different directory",
            details={"expected": str(expected_path), "actual": str(returned_path)},
        )


def _model_dict(model: Any) -> dict[str, Any] | None:
    if model is None:
        return None
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return dict(model)


def _write_local_artifacts(result_dir: Path, local: LocalGitArtifacts) -> None:
    (result_dir / "git-status.txt").write_text(local.status_short, encoding="utf-8")
    (result_dir / "git-diff-stat.txt").write_text(local.diff_stat, encoding="utf-8")
    (result_dir / "local-git-diff.patch").write_text(local.diff_binary, encoding="utf-8")
    (result_dir / "git-diff-numstat.txt").write_text(local.diff_numstat, encoding="utf-8")


def _count_status_files(status_short: str) -> int:
    count = 0
    for line in status_short.splitlines():
        if line.strip():
            count += 1
    return count


def _collect_local_best_effort(manager: GitWorktreeManager, worktree: Path, result_dir: Path) -> None:
    try:
        _write_local_artifacts(result_dir, manager.collect_local_artifacts(worktree))
    except Exception:
        return


def _record_prefix(record: CandidateManifestRecord) -> str:
    label = record.label or record.eval_id or record.id
    if label == record.id:
        return f"[{record.id}]"
    if len(label) > 40:
        label = f"{label[:37]}..."
    return f"[{record.id} {label}]"


def _print_run_context(
    console: Console,
    config: EvalConfig,
    *,
    run_id: str,
    repo_root: Path,
    base_sha: str,
    version: str,
    output_dir: Path,
    worktree_root: Path,
    candidate_count: int,
) -> None:
    console.print(f"opencode server: {config.server.url}", markup=False)
    console.print(f"opencode version: {version}", markup=False)
    console.print(f"run id: {run_id}", markup=False)
    console.print(f"repository: {repo_root}", markup=False)
    console.print(f"base ref: {config.repo.base_ref} ({base_sha})", markup=False)
    console.print(f"output dir: {output_dir}", markup=False)
    console.print(f"worktree root: {worktree_root}", markup=False)
    console.print(
        f"candidates: {candidate_count}; concurrency: {config.run.concurrency}",
        markup=False,
    )
    command = normalize_command(config.run.command)
    if command is None:
        console.print("opencode request: message", markup=False)
    else:
        console.print(f"opencode request: command /{command}", markup=False)
    console.print(f"validation commands: {len(config.validation.commands)}", markup=False)


def _worktree_path_slug(candidate_id: str) -> str:
    return sanitize_path_slug(candidate_id, fallback="candidate")


def _run_validation(config: EvalConfig, worktree: Path, result_dir: Path) -> dict[str, Any]:
    validation_dir = result_dir / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    passed = True
    for command_config in config.validation.commands:
        started_at = utc_now_iso()
        stdout_file = validation_dir / f"{command_config.name}.stdout.log"
        stderr_file = validation_dir / f"{command_config.name}.stderr.log"
        timed_out = False
        try:
            completed = subprocess.run(
                command_config.command,
                cwd=worktree,
                shell=True,
                text=True,
                capture_output=True,
                timeout=command_config.timeout_seconds,
                check=False,
            )
            exit_code = completed.returncode
            stdout_file.write_text(completed.stdout, encoding="utf-8")
            stderr_file.write_text(completed.stderr, encoding="utf-8")
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = 124
            stdout_file.write_text(
                (exc.stdout or "") if isinstance(exc.stdout, str) else "",
                encoding="utf-8",
            )
            stderr_file.write_text(
                (exc.stderr or "") if isinstance(exc.stderr, str) else "",
                encoding="utf-8",
            )
        completed_at = utc_now_iso()
        if command_config.required and (timed_out or exit_code != 0):
            passed = False
        records.append(
            {
                "name": command_config.name,
                "command": command_config.command,
                "cwd": str(worktree),
                "started_at": started_at,
                "completed_at": completed_at,
                "exit_code": exit_code,
                "timeout": timed_out,
                "stdout_file": str(stdout_file.relative_to(result_dir)),
                "stderr_file": str(stderr_file.relative_to(result_dir)),
                "required": command_config.required,
            }
        )
    return {"commands": records, "passed": passed}


def _abort_after_timeout(
    client: OpencodeClient,
    worktree: Path,
    session_id: str,
    error: ErrorRecord,
) -> None:
    try:
        client.session_abort(worktree, session_id)
    except Exception as exc:
        error.details["abort_error"] = str(exc)
    try:
        client.session_status(worktree)
    except Exception as exc:
        error.details["status_poll_error"] = str(exc)


def _update_manifest(
    manifest: Manifest,
    record: CandidateManifestRecord,
    *,
    session_id: str | None,
    status: str,
    lock: threading.Lock,
) -> None:
    with lock:
        manifest.upsert_candidate(
            CandidateManifestRecord(
                id=record.id,
                eval_id=record.eval_id,
                label=record.label,
                requested_branch_name=record.requested_branch_name,
                branch_name=record.branch_name,
                worktree_path=record.worktree_path,
                result_dir=record.result_dir,
                session_id=session_id,
                status=status,
            )
        )
        write_manifest(manifest)
