from __future__ import annotations

import json
import os
from pathlib import Path

from typer.testing import CliRunner

from eval_feia.cli import app
from eval_feia.manifest import (
    CandidateManifestRecord,
    Manifest,
    RepoRecord,
    ServerRecord,
    write_json,
    write_manifest,
)
from eval_feia.results_store import complete_run_record, run_directory, start_run_record


def test_top_level_help_uses_compact_command_names() -> None:
    result = CliRunner().invoke(app, ["--help"], color=False)

    assert result.exit_code == 0
    for command in ("run", "result", "clean"):
        assert command in result.output
    assert " ls " not in result.output
    assert "run-eval" not in result.output
    assert "list-run-artifacts" not in result.output


def test_run_help_lists_command_option() -> None:
    result = CliRunner().invoke(app, ["run", "--help"], color=False)

    assert result.exit_code == 0
    assert "--command" in result.output
    assert "Run an opencode slash command" in result.output
    assert "arguments" in result.output
    assert "--branch" in result.output
    assert "--attempts" in result.output
    assert "--jobs" in result.output
    assert "-j" in result.output
    assert "--repo" in result.output
    assert "--base-dir" in result.output
    assert "EVAL_FEIA_BASE_DIR" in result.output
    assert "--progress" in result.output
    assert "--quiet" not in result.output
    assert "--output-dir" not in result.output
    assert "--config" not in result.output
    assert "--base-ref" not in result.output
    assert "--worktrees" not in result.output
    assert "--branch-name" not in result.output
    assert "http://127.0.0.1:4096" in result.output
    assert "HEAD" in result.output


def test_run_accepts_canonical_args_and_prompt_argument(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    run_id = "20260517-143012-a1b2c3"
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(tmp_path / "stored-results"))
    monkeypatch.setattr("eval_feia.cli.generate_run_id", lambda: run_id)

    def fake_run_evaluation(config, *, console, run_id):
        captured["config"] = config
        captured["console"] = console
        captured["run_id"] = run_id

        class Outcome:
            passed = True
            output_dir = tmp_path / "artifacts" / run_id
            summary = {
                "run_id": run_id,
                "label": None,
                "server": {"url": "http://opencode.test"},
                "opencode_version": "fake",
                "repo": {"path": str(tmp_path), "base_ref": "main", "base_sha": "abc123"},
                "output_dir": str(output_dir),
                "passed": True,
                "health": {},
                "candidates": [],
            }

        return Outcome()

    monkeypatch.setattr("eval_feia.cli.run_evaluation", fake_run_evaluation)

    result = CliRunner().invoke(
        app,
        [
            "run",
            "hello inline",
            "--repo",
            str(tmp_path),
            "--branch",
            "main",
            "--attempts",
            "3",
            "--jobs",
            "2",
        ],
        color=False,
    )

    assert result.exit_code == 0
    assert captured["config"].run.prompt == "hello inline"
    assert captured["config"].repo.base_ref == "main"
    assert captured["config"].run.candidates == 3
    assert captured["config"].run.concurrency == 2
    assert captured["run_id"] == run_id
    assert f"Run ID: {run_id}" in result.output
    assert "Output directory:" in result.output
    metadata = json.loads((run_directory(run_id) / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "success"
    assert metadata["exit_code"] == 0


def test_run_base_dir_controls_config_and_stored_results(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    run_id = "20260517-143012-a1b2c3"
    base_dir = tmp_path / "state"
    monkeypatch.delenv("EVAL_FEIA_RESULTS_DIR", raising=False)
    monkeypatch.setattr("eval_feia.cli.generate_run_id", lambda: run_id)

    def fake_run_evaluation(config, *, console, run_id):
        captured["config"] = config

        class Outcome:
            passed = True
            output_dir = config.run.output_root / run_id / "output"
            summary = {
                "run_id": run_id,
                "label": None,
                "server": {"url": "http://opencode.test"},
                "opencode_version": "fake",
                "repo": {"path": str(tmp_path), "base_ref": "HEAD", "base_sha": "abc123"},
                "output_dir": str(output_dir),
                "passed": True,
                "health": {},
                "candidates": [],
            }

        return Outcome()

    monkeypatch.setattr("eval_feia.cli.run_evaluation", fake_run_evaluation)

    result = CliRunner().invoke(
        app,
        ["run", "hello inline", "--base-dir", str(base_dir)],
        color=False,
    )

    assert result.exit_code == 0
    assert captured["config"].run.output_root == base_dir.resolve(strict=False)
    assert captured["config"].repo.worktree_root == base_dir.resolve(strict=False)
    assert (base_dir / run_id / "results" / "metadata.json").exists()


def test_run_short_jobs_option_controls_concurrency(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    run_id = "20260517-143012-a1b2c3"
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(tmp_path / "stored-results"))
    monkeypatch.setattr("eval_feia.cli.generate_run_id", lambda: run_id)

    def fake_run_evaluation(config, *, console, run_id):
        captured["concurrency"] = config.run.concurrency

        class Outcome:
            passed = True
            output_dir = tmp_path / "artifacts" / run_id
            summary = {
                "run_id": run_id,
                "label": None,
                "server": {"url": "http://opencode.test"},
                "opencode_version": "fake",
                "repo": {"path": str(tmp_path), "base_ref": "HEAD", "base_sha": "abc123"},
                "output_dir": str(output_dir),
                "passed": True,
                "health": {},
                "candidates": [],
            }

        return Outcome()

    monkeypatch.setattr("eval_feia.cli.run_evaluation", fake_run_evaluation)

    result = CliRunner().invoke(
        app,
        ["run", "hello inline", "--attempts", "4", "-j", "3"],
        color=False,
    )

    assert result.exit_code == 0
    assert captured["concurrency"] == 3


def test_run_no_progress_disables_progress_logging(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    run_id = "20260517-143012-a1b2c3"
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(tmp_path / "stored-results"))
    monkeypatch.setattr("eval_feia.cli.generate_run_id", lambda: run_id)

    def fake_run_evaluation(config, *, console, run_id):
        captured["progress"] = config.run.progress

        class Outcome:
            passed = True
            output_dir = tmp_path / "artifacts" / run_id
            summary = {
                "run_id": run_id,
                "label": None,
                "server": {"url": "http://opencode.test"},
                "opencode_version": "fake",
                "repo": {"path": str(tmp_path), "base_ref": "HEAD", "base_sha": "abc123"},
                "output_dir": str(output_dir),
                "passed": True,
                "health": {},
                "candidates": [],
            }

        return Outcome()

    monkeypatch.setattr("eval_feia.cli.run_evaluation", fake_run_evaluation)

    result = CliRunner().invoke(app, ["run", "hello inline", "--no-progress"], color=False)

    assert result.exit_code == 0
    assert captured["progress"] is False


def test_run_rejects_invalid_jobs_values() -> None:
    zero = CliRunner().invoke(app, ["run", "hello inline", "--jobs", "0"], color=False)
    negative = CliRunner().invoke(app, ["run", "hello inline", "--jobs", "-1"], color=False)
    non_numeric = CliRunner().invoke(app, ["run", "hello inline", "--jobs", "many"], color=False)

    assert zero.exit_code == 2
    assert "--jobs must be greater than zero" in zero.output
    assert negative.exit_code == 2
    assert "--jobs must be greater than zero" in negative.output
    assert non_numeric.exit_code == 2
    assert "Invalid value" in non_numeric.output


def test_run_rejects_removed_config_and_alias_options() -> None:
    for option in (
        "--config",
        "--base-ref",
        "--worktrees",
        "--prompt",
        "--branch-name",
        "--output-dir",
    ):
        result = CliRunner().invoke(app, ["run", "hello inline", option, "value"], color=False)

        assert result.exit_code == 2

    quiet = CliRunner().invoke(app, ["run", "hello inline", "--quiet"], color=False)

    assert quiet.exit_code == 2


def test_run_rejects_prompt_argument_with_prompt_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(tmp_path / "stored-results"))
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("hello from file", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["run", "hello inline", "--prompt-file", str(prompt_file)],
        color=False,
    )

    assert result.exit_code == 2
    assert "provide only one prompt source" in result.output


def test_clean_manifest_is_positional_argument() -> None:
    result = CliRunner().invoke(app, ["clean", "--help"], color=False)

    assert result.exit_code == 0
    assert "MANIFEST" in result.output
    assert "--results" in result.output
    assert "--base-dir" in result.output
    assert "--db" not in result.output
    assert "--manifest" not in result.output


def test_list_help_includes_index_filters() -> None:
    result = CliRunner().invoke(app, ["result", "list", "--help"], color=False)

    assert result.exit_code == 0
    assert "--limit" in result.output
    assert "--status" in result.output
    assert "--branch" in result.output
    assert "--label" in result.output
    assert "--base-dir" in result.output
    assert "--output-dir" not in result.output
    assert "--json" in result.output


def test_result_help_includes_inspection_commands() -> None:
    result = CliRunner().invoke(app, ["result", "--help"], color=False)

    assert result.exit_code == 0
    for command in ("list", "show", "path", "file"):
        assert command in result.output


def test_list_can_inspect_stored_results(monkeypatch, tmp_path: Path) -> None:
    run_id = "20260517-143012-a1b2c3"
    root = tmp_path / "results"
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(root))
    start_run_record(run_id, cwd=tmp_path, branch="main", label="demo", command="bash")
    complete_run_record(
        run_id,
        status="success",
        exit_code=0,
        output_text="final output\n",
        summary_text="quick summary\n",
        stdout_text="stdout\n",
        stderr_text="",
    )

    listed = CliRunner().invoke(app, ["result", "list"], color=False)
    assert listed.exit_code == 0
    assert "RUN" in listed.output
    assert "STATUS" in listed.output
    assert run_id in listed.output
    assert "success" in listed.output

    removed_results = CliRunner().invoke(app, ["results", "show", run_id], color=False)
    assert removed_results.exit_code == 2
    removed_list = CliRunner().invoke(app, ["list"], color=False)
    assert removed_list.exit_code == 2

    shown = CliRunner().invoke(app, ["result", "show", run_id], color=False)
    assert shown.exit_code == 0
    assert "run_id: 20260517-143012-a1b2c3" in shown.output
    assert "status: success" in shown.output
    assert "quick summary" in shown.output

    path = CliRunner().invoke(app, ["result", "path", run_id], color=False)
    assert path.exit_code == 0
    assert path.output == f"{run_directory(run_id)}\n"

    output = CliRunner().invoke(app, ["result", "file", run_id], color=False)
    assert output.exit_code == 0
    assert output.output == "final output\n"

    metadata = CliRunner().invoke(app, ["result", "file", run_id, "metadata.json"], color=False)
    assert metadata.exit_code == 0
    assert '"run_id": "20260517-143012-a1b2c3"' in metadata.output


def test_result_show_rejects_listing_options(monkeypatch, tmp_path: Path) -> None:
    run_id = "20260517-143012-a1b2c3"
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(tmp_path / "results"))
    start_run_record(run_id, cwd=tmp_path, branch="main", label=None, command=None)

    result = CliRunner().invoke(app, ["result", "show", run_id, "--json"], color=False)

    assert result.exit_code == 2
    assert "No such option" in result.output


def test_results_show_falls_back_to_output_when_summary_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_id = "20260517-143012-a1b2c3"
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(tmp_path / "results"))
    start_run_record(run_id, cwd=tmp_path, branch="main", label=None, command=None)
    complete_run_record(
        run_id,
        status="success",
        exit_code=0,
        output_text="fallback output\n",
        summary_text="",
        stdout_text="",
        stderr_text="",
    )
    (run_directory(run_id) / "summary.txt").unlink()

    shown = CliRunner().invoke(app, ["result", "show", run_id], color=False)

    assert shown.exit_code == 0
    assert "fallback output" in shown.output


def test_clean_rejects_ambiguous_results_options(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    with_manifest = CliRunner().invoke(app, ["clean", str(manifest), "--results"], color=False)
    with_force = CliRunner().invoke(app, ["clean", "--results", "--force"], color=False)
    without_manifest = CliRunner().invoke(app, ["clean"], color=False)

    assert with_manifest.exit_code == 2
    assert "MANIFEST cannot be used with --results" in with_manifest.output
    assert with_force.exit_code == 2
    assert "--force applies only to manifest cleanup" in with_force.output
    assert without_manifest.exit_code == 2
    assert "MANIFEST is required unless --results is set" in without_manifest.output


def test_clean_results_removes_configured_results_root(monkeypatch, tmp_path: Path) -> None:
    run_id = "20260517-143012-a1b2c3"
    root = tmp_path / "results"
    monkeypatch.setenv("EVAL_FEIA_RESULTS_DIR", str(root))
    start_run_record(run_id, cwd=tmp_path, branch="HEAD", label=None, command=None)
    complete_run_record(
        run_id,
        status="success",
        exit_code=0,
        output_text="ok\n",
        summary_text="ok\n",
        stdout_text="",
        stderr_text="",
    )

    dry_run = CliRunner().invoke(app, ["clean", "--results", "--dry-run"], color=False)

    assert dry_run.exit_code == 0
    assert f"would remove results: {root.resolve(strict=False)}" in dry_run.output
    assert root.exists()

    cleaned = CliRunner().invoke(app, ["clean", "--results"], color=False)

    assert cleaned.exit_code == 0
    assert f"removed results: {root.resolve(strict=False)}" in cleaned.output
    assert not root.exists()


def test_clean_results_uses_base_dir(monkeypatch, tmp_path: Path) -> None:
    run_id = "20260517-143012-a1b2c3"
    base_dir = tmp_path / "state"
    monkeypatch.delenv("EVAL_FEIA_RESULTS_DIR", raising=False)
    start_run_record(
        run_id,
        cwd=tmp_path,
        branch="HEAD",
        label=None,
        command=None,
        root=base_dir / run_id / "results",
    )
    complete_run_record(
        run_id,
        status="success",
        exit_code=0,
        output_text="ok\n",
        summary_text="ok\n",
        stdout_text="",
        stderr_text="",
        root=base_dir / run_id / "results",
    )

    result = CliRunner().invoke(
        app,
        ["clean", "--results", "--base-dir", str(base_dir), "--dry-run"],
        color=False,
    )

    assert result.exit_code == 0
    assert f"would remove results: {(base_dir / run_id / 'results').resolve(strict=False)}" in result.output


def test_list_empty_state_is_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = CliRunner().invoke(app, ["result", "list"], color=False)

    assert result.exit_code == 0
    assert "No saved runs found." in result.output


def test_list_outputs_metadata(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    run_dir = _write_saved_run(tmp_path, "run-1", label="nightly", branch_name="eval/run-1/main")

    result = CliRunner().invoke(app, ["result", "list"], color=False)

    assert result.exit_code == 0
    assert "run-1" in result.output
    assert "nightly" in result.output
    assert "eval/run-1/main" in result.output
    assert str(run_dir) in result.output
    assert str(run_dir / "run-summary.json") in result.output


def test_long_command_names_are_not_registered() -> None:
    for command in (
        "run-eval",
        "list-run-artifacts",
        "list-stored-results",
        "show-stored-result",
        "print-stored-result-path",
        "print-stored-result-file",
        "clean-run-artifacts",
        "clean-stored-results",
        "list",
        "results",
        "ls",
    ):
        result = CliRunner().invoke(app, [command, "--help"], color=False)

        assert result.exit_code == 2


def test_list_limit_shows_most_recent_runs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    old_run = _write_saved_run(tmp_path, "old-run", branch_name="eval/old-run/main")
    new_run = _write_saved_run(tmp_path, "new-run", branch_name="eval/new-run/main")
    _touch_run(old_run, 1_700_000_000)
    _touch_run(new_run, 1_800_000_000)

    result = CliRunner().invoke(app, ["result", "list", "--limit", "1"], color=False)

    assert result.exit_code == 0
    assert "new-run" in result.output
    assert "old-run" not in result.output


def test_list_rejects_removed_output_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = CliRunner().invoke(
        app,
        ["result", "list", "--output-dir", str(tmp_path / "custom-runs")],
        color=False,
    )

    assert result.exit_code == 2


def test_list_base_dir_reads_base_runs_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    base_dir = tmp_path / "state"
    run_dir = _write_saved_run(
        tmp_path,
        "base-run",
        output_root=base_dir,
        label="base label",
        branch_name="eval/base-run/main",
    )

    result = CliRunner().invoke(app, ["result", "list", "--base-dir", str(base_dir)], color=False)

    assert result.exit_code == 0
    assert "base-run" in result.output
    assert "base label" in result.output
    assert str(run_dir) in result.output


def test_list_base_dir_reads_stored_results_without_generated_output(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    base_dir = tmp_path / "state"
    run_id = "stored-only-run"
    results_root = base_dir / run_id / "results"
    start_run_record(run_id, cwd=tmp_path, branch="HEAD", label="stored only", command=None, root=results_root)
    complete_run_record(
        run_id,
        status="success",
        exit_code=0,
        output_text="ok\n",
        summary_text="ok\n",
        stdout_text="",
        stderr_text="",
        root=results_root,
    )

    result = CliRunner().invoke(app, ["result", "list", "--base-dir", str(base_dir)], color=False)

    assert result.exit_code == 0
    assert run_id in result.output
    assert "stored only" in result.output
    assert str(results_root) in result.output


def test_list_filters_read_base_runs_root_when_empty(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    base_dir = tmp_path / "state"

    result = CliRunner().invoke(
        app,
        ["result", "list", "--base-dir", str(base_dir), "--status", "success"],
        color=False,
    )

    assert result.exit_code == 0
    assert "No saved runs found." in result.output


def test_list_json_outputs_saved_runs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    run_dir = _write_saved_run(tmp_path, "run-1", label="nightly", branch_name="eval/run-1/main")

    result = CliRunner().invoke(app, ["result", "list", "--json"], color=False)

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["run_id"] == "run-1"
    assert payload[0]["created_at"] == "2026-05-14T12:34:56+00:00"
    assert isinstance(payload[0]["modified_at"], str)
    assert payload[0]["label"] == "nightly"
    assert payload[0]["branches"] == ["eval/run-1/main"]
    assert payload[0]["output_path"] == str(run_dir)
    assert payload[0]["result_path"] == str(run_dir / "run-summary.json")
    assert payload[0]["metadata_path"] == str(run_dir / "manifest.json")
    assert payload[0]["warning"] is None


def test_list_tolerates_broken_metadata(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    run_dir = tmp_path / ".eval-feia" / "runs" / "broken-run"
    run_dir.mkdir(parents=True)
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text("{not json", encoding="utf-8")

    result = CliRunner().invoke(app, ["result", "list"], color=False)

    assert result.exit_code == 0
    assert "warning: broken-run: failed to parse manifest.json" in result.output
    assert "broken-run" in result.output
    assert str(manifest_path) in result.output


def _write_saved_run(
    base_dir: Path,
    run_id: str,
    *,
    output_root: Path | None = None,
    label: str | None = None,
    branch_name: str = "eval/run/cand-001",
) -> Path:
    root = output_root or base_dir / ".eval-feia"
    output_dir = (root / run_id / "output").resolve(strict=False)
    worktree_root = (root / run_id / "worktrees").resolve(strict=False)
    result_dir = output_dir / "candidates" / "cand-001"
    result_dir.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(
        run_id=run_id,
        label=label,
        created_at="2026-05-14T12:34:56+00:00",
        repo=RepoRecord(path=base_dir, base_ref="HEAD", base_sha="abc123"),
        server=ServerRecord(url="http://127.0.0.1:4096", version="test"),
        output_dir=output_dir,
        worktree_root=worktree_root,
        candidates=[
            CandidateManifestRecord(
                id="cand-001",
                branch_name=branch_name,
                worktree_path=worktree_root / "cand-001",
                result_dir=result_dir,
                session_id="ses_1",
                status="passed",
            )
        ],
    )
    write_manifest(manifest)
    write_json(
        output_dir / "run-summary.json",
        {
            "run_id": run_id,
            "label": label,
            "output_dir": str(output_dir),
            "passed": True,
            "candidates": [{"candidate_id": "cand-001", "branch_name": branch_name}],
        },
    )
    return output_dir


def _touch_run(run_dir: Path, timestamp: float) -> None:
    for path in [run_dir, run_dir / "manifest.json", run_dir / "run-summary.json"]:
        os.utime(path, (timestamp, timestamp))
