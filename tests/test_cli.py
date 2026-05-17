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


def test_run_help_lists_command_option() -> None:
    result = CliRunner().invoke(app, ["run", "--help"], color=False)

    assert result.exit_code == 0
    assert "--command" in result.output
    assert "Run an opencode slash command" in result.output
    assert "arguments" in result.output
    assert "--branch" in result.output
    assert "--attempts" in result.output
    assert "--config" not in result.output
    assert "--base-ref" not in result.output
    assert "--worktrees" not in result.output
    assert "--branch-name" not in result.output
    assert "http://127.0.0.1:4096" in result.output
    assert "HEAD" in result.output


def test_run_accepts_canonical_args_and_prompt_argument(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_run_evaluation(config, *, console):
        captured["config"] = config
        captured["console"] = console

        class Outcome:
            passed = True

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
        ],
        color=False,
    )

    assert result.exit_code == 0
    assert captured["config"].run.prompt == "hello inline"
    assert captured["config"].repo.base_ref == "main"
    assert captured["config"].run.candidates == 3


def test_run_rejects_removed_config_and_alias_options() -> None:
    for option in ("--config", "--base-ref", "--worktrees", "--prompt", "--branch-name"):
        result = CliRunner().invoke(app, ["run", "hello inline", option, "value"], color=False)

        assert result.exit_code == 2


def test_run_rejects_prompt_argument_with_prompt_file(tmp_path: Path) -> None:
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
    assert "--manifest" not in result.output


def test_list_empty_state_is_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["list"], color=False)

    assert result.exit_code == 0
    assert "No saved runs found." in result.output


def test_list_saved_runs_outputs_metadata(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    run_dir = _write_saved_run(tmp_path, "run-1", label="nightly", branch_name="eval/run-1/main")

    result = CliRunner().invoke(app, ["list"], color=False)

    assert result.exit_code == 0
    assert "run-1" in result.output
    assert "nightly" in result.output
    assert "eval/run-1/main" in result.output
    assert str(run_dir) in result.output
    assert str(run_dir / "run-summary.json") in result.output


def test_ls_alias_matches_list(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _write_saved_run(tmp_path, "run-1", label="nightly", branch_name="eval/run-1/main")

    list_result = CliRunner().invoke(app, ["list"], color=False)
    ls_result = CliRunner().invoke(app, ["ls"], color=False)

    assert list_result.exit_code == 0
    assert ls_result.exit_code == 0
    assert ls_result.output == list_result.output


def test_list_limit_shows_most_recent_runs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    old_run = _write_saved_run(tmp_path, "old-run", branch_name="eval/old-run/main")
    new_run = _write_saved_run(tmp_path, "new-run", branch_name="eval/new-run/main")
    _touch_run(old_run, 1_700_000_000)
    _touch_run(new_run, 1_800_000_000)

    result = CliRunner().invoke(app, ["list", "--limit", "1"], color=False)

    assert result.exit_code == 0
    assert "new-run" in result.output
    assert "old-run" not in result.output


def test_list_output_dir_reads_custom_root_for_list_and_ls(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    output_root = tmp_path / "custom-runs"
    run_dir = _write_saved_run(
        tmp_path,
        "custom-run",
        output_root=output_root,
        label="custom label",
        branch_name="eval/custom-run/main",
    )

    default_result = CliRunner().invoke(app, ["list"], color=False)
    list_result = CliRunner().invoke(
        app,
        ["list", "--output-dir", str(output_root)],
        color=False,
    )
    ls_result = CliRunner().invoke(
        app,
        ["ls", "--output-dir", str(output_root)],
        color=False,
    )

    assert default_result.exit_code == 0
    assert "No saved runs found." in default_result.output
    assert list_result.exit_code == 0
    assert ls_result.exit_code == 0
    assert list_result.output == ls_result.output
    assert "custom-run" in list_result.output
    assert "custom label" in list_result.output
    assert "eval/custom-run/main" in list_result.output
    assert str(run_dir) in list_result.output


def test_list_json_outputs_saved_runs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    run_dir = _write_saved_run(tmp_path, "run-1", label="nightly", branch_name="eval/run-1/main")

    result = CliRunner().invoke(app, ["list", "--json"], color=False)

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
    run_dir = tmp_path / ".eval-feia" / "runs" / "broken-run"
    run_dir.mkdir(parents=True)
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text("{not json", encoding="utf-8")

    result = CliRunner().invoke(app, ["list"], color=False)

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
    root = output_root or base_dir / ".eval-feia" / "runs"
    output_dir = (root / run_id).resolve(strict=False)
    worktree_root = (base_dir / ".eval-feia" / "worktrees" / run_id).resolve(strict=False)
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
