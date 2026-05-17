from __future__ import annotations

import json
import io
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import httpx
from rich.console import Console

from eval_feia.config import EvalConfig
from eval_feia.opencode_client import DIRECTORY_HEADER, OpencodeClient
from eval_feia.runner import _health_with_retry, run_evaluation
from eval_feia.storage import default_db_path, list_runs


def test_runner_success_collects_children_validation_and_summary(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    prompt = repo / "prompt.md"
    prompt.write_text("Do a no-op task.\n", encoding="utf-8")
    seen: list[httpx.Request] = []
    health_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal health_calls
        seen.append(request)
        if request.url.path == "/global/health":
            health_calls += 1
            if health_calls == 1:
                return httpx.Response(503, json={"healthy": False})
            return httpx.Response(200, json={"healthy": True, "version": "fake-1"})
        cwd = _request_cwd(request)
        if request.url.path == "/path":
            return httpx.Response(200, json={"path": cwd})
        if request.url.path in {"/project/current", "/config", "/vcs"}:
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/session" and request.method == "POST":
            body = json.loads(request.content.decode())
            assert body == {"title": "eval-feia/test-run/cand-001"}
            return httpx.Response(200, json={"id": "ses_1", "directory": cwd})
        if request.url.path == "/session/ses_1/message" and request.method == "POST":
            body = json.loads(request.content.decode())
            assert body["parts"] == [{"type": "text", "text": "Do a no-op task.\n"}]
            assert body["agent"] == "build"
            Path(cwd, "new-file.txt").write_text("created by fake opencode\n", encoding="utf-8")
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/session/ses_1":
            return httpx.Response(200, json={"id": "ses_1", "directory": cwd})
        if request.url.path == "/session/ses_1/message":
            return httpx.Response(
                200,
                json=[{"role": "assistant", "parts": [{"type": "text", "text": "finished"}]}],
            )
        if request.url.path == "/session/ses_1/children":
            return httpx.Response(200, json=[{"id": "ses_child"}])
        if request.url.path == "/session/ses_child":
            return httpx.Response(200, json={"id": "ses_child", "directory": cwd})
        if request.url.path == "/session/ses_child/message":
            return httpx.Response(200, json=[])
        if request.url.path == "/session/ses_child/children":
            return httpx.Response(200, json=[])
        if request.url.path == "/session/ses_child/diff":
            return httpx.Response(200, json={})
        if request.url.path == "/session/ses_1/todo":
            return httpx.Response(200, json=[])
        if request.url.path == "/session/ses_1/diff":
            return httpx.Response(200, json={"files": []})
        if request.url.path == "/file/status":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    config = _config(
        repo,
        prompt,
        candidates=1,
        validation_command=f'"{sys.executable}" -c "print(123)"',
    )
    client = OpencodeClient("http://opencode.test", transport=httpx.MockTransport(handler))
    outcome = run_evaluation(
        config,
        client=client,
        console=Console(file=io.StringIO()),
        run_id="test-run",
    )

    assert outcome.passed is True
    assert health_calls == 2
    result_dir = outcome.output_dir / "candidates" / "cand-001"
    assert (result_dir / "final-output.md").read_text(encoding="utf-8") == "finished\n"
    children = json.loads((result_dir / "children.json").read_text(encoding="utf-8"))
    assert children[0]["id"] == "ses_child"
    assert (outcome.output_dir / "run-summary.json").exists()
    assert outcome.summary["candidates"][0]["summary"]["files_changed"] == 1
    indexed = list_runs(default_db_path(config.run.output_root), status="success")
    assert indexed[0]["id"] == "test-run"
    assert indexed[0]["branch"] == "HEAD"
    assert indexed[0]["output_dir"] == str(outcome.output_dir)
    assert indexed[0]["summary_path"] == str(outcome.output_dir / "run-summary.json")
    assert any(req.url.path == "/session/ses_1/message" and req.method == "POST" for req in seen)
    assert not any("prompt_async" in req.url.path for req in seen)
    for request in seen:
        if request.url.path == "/global/health":
            continue
        if request.method == "GET":
            assert request.url.query.decode().startswith("directory=")
        else:
            assert DIRECTORY_HEADER in request.headers


def test_runner_command_posts_command_endpoint(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    prompt = repo / "prompt.md"
    prompt.write_text("git status 확인해줘", encoding="utf-8")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        cwd = _request_cwd(request) if request.url.path != "/global/health" else ""
        if request.url.path == "/global/health":
            return httpx.Response(200, json={"healthy": True, "version": "fake"})
        if request.url.path in {"/path", "/project/current", "/config", "/vcs"}:
            return httpx.Response(200, json={"path": cwd})
        if request.url.path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": "ses_1", "directory": cwd})
        if request.url.path == "/session/ses_1/command" and request.method == "POST":
            body = json.loads(request.content.decode())
            assert body == {
                "agent": "build",
                "arguments": "git status 확인해줘",
                "command": "bash",
                "model": "p/m",
            }
            assert "parts" not in body
            Path(cwd, "command-output.txt").write_text("created by fake command\n", encoding="utf-8")
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/session/ses_1":
            return httpx.Response(200, json={"id": "ses_1", "directory": cwd})
        if request.url.path == "/session/ses_1/message":
            return httpx.Response(
                200,
                json=[{"role": "assistant", "parts": [{"type": "text", "text": "command done"}]}],
            )
        if request.url.path == "/session/ses_1/children":
            return httpx.Response(200, json=[])
        if request.url.path == "/session/ses_1/todo":
            return httpx.Response(200, json=[])
        if request.url.path == "/session/ses_1/diff":
            return httpx.Response(200, json={})
        if request.url.path == "/file/status":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    config = _config(repo, prompt, command="/bash", model={"providerID": "p", "modelID": "m"})
    client = OpencodeClient("http://opencode.test", transport=httpx.MockTransport(handler))
    outcome = run_evaluation(
        config,
        client=client,
        console=Console(file=io.StringIO()),
        run_id="command-run",
    )

    assert outcome.passed is True
    assert any(req.url.path == "/session/ses_1/command" and req.method == "POST" for req in seen)
    assert not any(req.url.path == "/session/ses_1/message" and req.method == "POST" for req in seen)


def test_runner_uses_inline_prompt(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    seen_prompt = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_prompt
        cwd = _request_cwd(request) if request.url.path != "/global/health" else ""
        if request.url.path == "/global/health":
            return httpx.Response(200, json={"healthy": True, "version": "fake"})
        if request.url.path in {"/path", "/project/current", "/config", "/vcs"}:
            return httpx.Response(200, json={"path": cwd})
        if request.url.path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": "ses_1", "directory": cwd})
        if request.url.path == "/session/ses_1/message" and request.method == "POST":
            body = json.loads(request.content.decode())
            seen_prompt = body["parts"][0]["text"]
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/session/ses_1":
            return httpx.Response(200, json={"id": "ses_1", "directory": cwd})
        if request.url.path == "/session/ses_1/message":
            return httpx.Response(200, json=[])
        if request.url.path == "/session/ses_1/children":
            return httpx.Response(200, json=[])
        if request.url.path == "/session/ses_1/todo":
            return httpx.Response(200, json=[])
        if request.url.path == "/session/ses_1/diff":
            return httpx.Response(200, json={})
        if request.url.path == "/file/status":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    config = _config(repo, prompt=None, prompt_text="hello inline")
    client = OpencodeClient("http://opencode.test", transport=httpx.MockTransport(handler))
    outcome = run_evaluation(
        config,
        client=client,
        console=Console(file=io.StringIO()),
        run_id="inline-prompt-run",
    )

    assert outcome.passed is True
    assert seen_prompt == "hello inline"


def test_runner_timeout_aborts_and_collects_partial_artifacts(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    prompt = repo / "prompt.md"
    prompt.write_text("timeout\n", encoding="utf-8")
    aborted = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal aborted
        cwd = _request_cwd(request) if request.url.path != "/global/health" else ""
        if request.url.path == "/global/health":
            return httpx.Response(200, json={"healthy": True, "version": "fake"})
        if request.url.path in {"/path", "/project/current", "/config", "/vcs"}:
            return httpx.Response(200, json={"path": cwd})
        if request.url.path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": "ses_timeout", "directory": cwd})
        if request.url.path == "/session/ses_timeout/message" and request.method == "POST":
            raise httpx.ReadTimeout("simulated timeout", request=request)
        if request.url.path == "/session/ses_timeout/abort":
            aborted = True
            return httpx.Response(204)
        if request.url.path == "/session/status":
            return httpx.Response(200, json={"ses_timeout": {"type": "idle"}})
        if request.url.path == "/session/ses_timeout":
            return httpx.Response(200, json={"id": "ses_timeout", "directory": cwd})
        if request.url.path == "/session/ses_timeout/message":
            return httpx.Response(200, json=[])
        if request.url.path == "/session/ses_timeout/children":
            return httpx.Response(200, json=[])
        if request.url.path == "/session/ses_timeout/todo":
            return httpx.Response(200, json=[])
        if request.url.path == "/session/ses_timeout/diff":
            return httpx.Response(200, json={})
        if request.url.path == "/file/status":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    config = _config(repo, prompt, timeout_seconds=0.01)
    client = OpencodeClient("http://opencode.test", transport=httpx.MockTransport(handler))
    outcome = run_evaluation(
        config,
        client=client,
        console=Console(file=io.StringIO()),
        run_id="timeout-run",
    )
    assert outcome.passed is False
    assert aborted is True
    error = json.loads(
        (outcome.output_dir / "candidates" / "cand-001" / "error.json").read_text(
            encoding="utf-8"
        )
    )
    assert error["kind"] == "timeout"


def test_runner_required_validation_failure_fails_candidate(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    prompt = repo / "prompt.md"
    prompt.write_text("validate\n", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        cwd = _request_cwd(request) if request.url.path != "/global/health" else ""
        if request.url.path == "/global/health":
            return httpx.Response(200, json={"healthy": True, "version": "fake"})
        if request.url.path in {"/path", "/project/current", "/config", "/vcs"}:
            return httpx.Response(200, json={"path": cwd})
        if request.url.path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": "ses_1", "directory": cwd})
        if request.url.path == "/session/ses_1/message" and request.method == "POST":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/session/ses_1":
            return httpx.Response(200, json={"id": "ses_1", "directory": cwd})
        if request.url.path == "/session/ses_1/message":
            return httpx.Response(200, json=[])
        if request.url.path == "/session/ses_1/children":
            return httpx.Response(200, json=[])
        if request.url.path == "/session/ses_1/todo":
            return httpx.Response(200, json=[])
        if request.url.path == "/session/ses_1/diff":
            return httpx.Response(200, json={})
        if request.url.path == "/file/status":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    config = _config(
        repo,
        prompt,
        validation_command=f'"{sys.executable}" -c "import sys; sys.exit(7)"',
    )
    client = OpencodeClient("http://opencode.test", transport=httpx.MockTransport(handler))
    outcome = run_evaluation(
        config,
        client=client,
        console=Console(file=io.StringIO()),
        run_id="validation-run",
    )
    assert outcome.passed is False
    result = json.loads(
        (outcome.output_dir / "candidates" / "cand-001" / "result.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["error"]["kind"] == "validation_failed"


def test_runner_records_resolved_branch_names_labels_and_worktrees(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    sessions: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        cwd = _request_cwd(request) if request.url.path != "/global/health" else ""
        if request.url.path == "/global/health":
            return httpx.Response(200, json={"healthy": True, "version": "fake"})
        if request.url.path in {"/path", "/project/current", "/config", "/vcs"}:
            return httpx.Response(200, json={"path": cwd})
        if request.url.path == "/session" and request.method == "POST":
            session_id = f"ses_{len(sessions) + 1}"
            sessions[session_id] = cwd
            return httpx.Response(200, json={"id": session_id, "directory": cwd})
        if request.url.path.endswith("/message") and request.method == "POST":
            return httpx.Response(200, json={"ok": True})

        parts = request.url.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "session":
            session_id = parts[1]
            if len(parts) == 2:
                return httpx.Response(200, json={"id": session_id, "directory": cwd})
            if len(parts) == 3 and parts[2] == "message":
                return httpx.Response(200, json=[])
            if len(parts) == 3 and parts[2] in {"children", "todo"}:
                return httpx.Response(200, json=[])
            if len(parts) == 3 and parts[2] == "diff":
                return httpx.Response(200, json={})
        if request.url.path == "/file/status":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    config = EvalConfig.model_validate(
        {
            "server": {"url": "http://opencode.test", "health_retries": 1},
            "repo": {
                "path": repo,
                "base_ref": "HEAD",
                "worktree_root": repo / ".eval-feia" / "worktrees",
            },
            "run": {
                "output_root": repo / ".eval-feia" / "runs",
                "concurrency": 1,
                "timeout_seconds": 5,
                "label": "branch run label",
            },
            "evals": [
                {
                    "id": "one",
                    "prompt": "first",
                    "branch_name": "eval/duplicate",
                },
                {
                    "id": "two",
                    "prompt": "second",
                    "branch_name": "eval/duplicate",
                },
            ],
            "validation": {"commands": []},
            "summary": {},
        }
    )
    output = io.StringIO()
    client = OpencodeClient("http://opencode.test", transport=httpx.MockTransport(handler))

    outcome = run_evaluation(
        config,
        client=client,
        console=Console(file=output, width=240),
        run_id="branch-run",
    )

    assert outcome.passed is True
    assert outcome.summary["label"] == "branch run label"
    candidates = outcome.summary["candidates"]
    assert "eval_id" not in candidates[0]
    assert "label" not in candidates[0]
    assert candidates[0]["base_ref"] == "HEAD"
    assert candidates[0]["base_sha"] == outcome.summary["repo"]["base_sha"]
    assert candidates[0]["requested_branch_name"] == "eval/duplicate"
    assert candidates[0]["branch_name"] == "eval/branch-run/duplicate"
    assert Path(candidates[0]["worktree_path"]).name == "one"
    assert "eval_id" not in candidates[1]
    assert "label" not in candidates[1]
    assert candidates[1]["requested_branch_name"] == "eval/duplicate"
    assert candidates[1]["branch_name"] == "eval/branch-run/duplicate-2"
    assert Path(candidates[1]["worktree_path"]).name == "two"

    result = json.loads(
        (outcome.output_dir / "candidates" / "two" / "result.json").read_text(
            encoding="utf-8"
        )
    )
    assert "label" not in result
    assert "eval_id" not in result
    assert result["base_ref"] == "HEAD"
    assert result["base_sha"] == outcome.summary["repo"]["base_sha"]
    assert result["requested_branch_name"] == "eval/duplicate"
    assert result["branch_name"] == "eval/branch-run/duplicate-2"
    assert result["worktree_path"] == candidates[1]["worktree_path"]

    summary = json.loads(
        (outcome.output_dir / "run-summary.json").read_text(encoding="utf-8")
    )
    assert summary["candidates"][1]["branch_name"] == "eval/branch-run/duplicate-2"
    manifest = json.loads(
        (outcome.output_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["label"] == "branch run label"
    assert "eval_id" not in manifest["candidates"][1]
    assert manifest["candidates"][1]["branch_name"] == "eval/branch-run/duplicate-2"
    assert "progress: checking opencode server" in output.getvalue()
    assert "progress: preparing output directories" in output.getvalue()
    assert "run id: branch-run" in output.getvalue()
    assert "label: branch run label" in output.getvalue()
    assert "base ref: HEAD (" in output.getvalue()
    assert "worktree root:" in output.getvalue()
    assert "candidates: 2; concurrency: 1" in output.getvalue()
    assert "opencode request: message" in output.getvalue()
    assert "validation commands: 0" in output.getvalue()
    assert "progress: creating worktrees" in output.getvalue()
    worktree_table_output = output.getvalue().split("[one] session:", 1)[0]
    assert "WORKTREE" in worktree_table_output
    assert "CANDIDATE" not in worktree_table_output
    assert "BRANCH" not in worktree_table_output
    assert f"1  {candidates[0]['worktree_path']}" in worktree_table_output
    assert f"2  {candidates[1]['worktree_path']}" in worktree_table_output
    assert "1/2" not in worktree_table_output
    assert "eval/branch-run/duplicate" not in worktree_table_output
    assert "[1/2] candidate: one" not in worktree_table_output
    assert "progress: running candidates" in output.getvalue()
    assert "progress: writing final summary" in output.getvalue()
    summary_output = output.getvalue().split("progress: writing final summary", 1)[1]
    assert "eval-feia results" in summary_output
    assert "CANDIDATE  BRANCH" in summary_output
    assert "eval/branch-run/duplicate" in summary_output
    assert "eval/branch-run/duplicate-2" in summary_output
    assert "┏" not in summary_output
    assert "│" not in summary_output


def test_health_retry_uses_dedicated_timeout() -> None:
    class FakeClient(OpencodeClient):
        def __init__(self) -> None:
            self.timeouts: list[float | None] = []

        def health(self, *, timeout: float | None = None) -> dict[str, object]:
            self.timeouts.append(timeout)
            if len(self.timeouts) == 1:
                return {"healthy": False}
            return {"healthy": True, "version": "fake"}

    config = EvalConfig.model_validate(
        {
            "server": {
                "url": "http://opencode.test",
                "health_retries": 2,
                "health_interval_ms": 0,
                "health_timeout_seconds": 1.25,
            },
            "run": {"prompt": "hello"},
        }
    )
    client = FakeClient()

    health = _health_with_retry(client, config)

    assert health["version"] == "fake"
    assert client.timeouts == [1.25, 1.25]


def _config(
    repo: Path,
    prompt: Path | None,
    *,
    prompt_text: str | None = None,
    candidates: int = 1,
    timeout_seconds: float = 5,
    command: str | None = None,
    model: dict[str, str] | None = None,
    validation_command: str | None = None,
) -> EvalConfig:
    validation: dict[str, object] = {"commands": []}
    if validation_command:
        validation = {
            "commands": [
                {
                    "name": "check",
                    "command": validation_command,
                    "timeout_seconds": 5,
                    "required": True,
                }
            ]
        }
    return EvalConfig.model_validate(
        {
            "server": {
                "url": "http://opencode.test",
                "health_retries": 3,
                "health_interval_ms": 1,
            },
            "repo": {
                "path": repo,
                "base_ref": "HEAD",
                "worktree_root": repo / ".eval-feia" / "worktrees",
            },
            "run": {
                "output_root": repo / ".eval-feia" / "runs",
                "candidates": candidates,
                "concurrency": min(candidates, 2),
                "timeout_seconds": timeout_seconds,
                "prompt": prompt_text,
                "prompt_file": prompt,
                "agent": "build",
                "model": model,
                "command": command,
            },
            "validation": validation,
            "summary": {},
        }
    )


def _request_cwd(request: httpx.Request) -> str:
    if request.method == "GET":
        query = request.url.query.decode()
        assert query.startswith("directory=")
        return unquote(query.split("=", 1)[1])
    assert DIRECTORY_HEADER in request.headers
    return unquote(request.headers[DIRECTORY_HEADER])


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=eval-feia",
            "-c",
            "user.email=eval-feia@example.test",
            "commit",
            "-m",
            "init",
        ],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return path.resolve()
