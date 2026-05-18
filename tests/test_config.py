from __future__ import annotations

from pathlib import Path

import pytest

from eval_feia.config import EvalConfig, build_config, resolve_config_paths
from eval_feia.errors import ConfigError
from eval_feia.runner import _build_candidate_specs


def test_build_config_maps_cli_inputs_and_resolves_paths(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    output_dir = tmp_path / "runs"
    prompt.write_text("hello", encoding="utf-8")

    config = build_config(
        server_url="http://opencode.test",
        repo=Path("repo"),
        base_ref="main",
        candidates=3,
        prompt_file=Path("prompt.md"),
        label="foo test",
        command="/bash",
        output_dir=Path("runs"),
        base_dir=tmp_path,
    )

    assert config.server.url == "http://opencode.test"
    assert config.repo.path == (tmp_path / "repo").resolve(strict=False)
    assert config.repo.base_ref == "main"
    assert config.run.candidates == 3
    assert config.run.prompt_file == prompt.resolve(strict=False)
    assert config.run.label == "foo test"
    assert config.run.command == "/bash"
    assert config.run.output_root == output_dir.resolve(strict=False)


def test_build_config_derives_run_and_worktree_roots_from_base_dir(tmp_path: Path) -> None:
    base_dir = tmp_path / "state"

    config = build_config(prompt="hello", base_root=Path("state"), base_dir=tmp_path)

    assert config.run.output_root == base_dir.resolve(strict=False)
    assert config.repo.worktree_root == base_dir.resolve(strict=False)


def test_default_roots_follow_base_dir_environment(monkeypatch, tmp_path: Path) -> None:
    base_dir = tmp_path / "state"
    monkeypatch.setenv("EVAL_FEIA_BASE_DIR", str(base_dir))

    config = build_config(prompt="hello", base_dir=tmp_path)

    assert config.run.output_root == base_dir.resolve(strict=False)
    assert config.repo.worktree_root == base_dir.resolve(strict=False)


def test_default_roots_use_home_base(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("EVAL_FEIA_BASE_DIR", raising=False)

    config = build_config(prompt="hello", base_dir=tmp_path)

    assert config.run.output_root == (home / ".eval-feia").resolve(strict=False)
    assert config.repo.worktree_root == (home / ".eval-feia").resolve(strict=False)


def test_build_config_accepts_inline_prompt(tmp_path: Path) -> None:
    config = build_config(prompt="hello from cli", base_dir=tmp_path)

    assert config.run.prompt == "hello from cli"
    assert config.run.prompt_file is None


def test_build_config_rejects_missing_prompt(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="run.prompt_file or run.prompt is required"):
        build_config(base_dir=tmp_path)


def test_build_config_rejects_prompt_and_prompt_file_together(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("hello", encoding="utf-8")

    with pytest.raises(ConfigError, match="mutually exclusive"):
        build_config(prompt="hello inline", prompt_file=prompt, base_dir=tmp_path)


def test_build_config_rejects_credentialed_server_url(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="must not include credentials"):
        build_config(server_url="http://user:secret@127.0.0.1:4096", prompt="hello", base_dir=tmp_path)


def test_build_config_rejects_server_url_query_or_fragment(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="query, or fragment"):
        build_config(server_url="http://127.0.0.1:4096?token=secret", prompt="hello", base_dir=tmp_path)

    with pytest.raises(ConfigError, match="query, or fragment"):
        build_config(server_url="http://127.0.0.1:4096/#secret", prompt="hello", base_dir=tmp_path)


def test_eval_config_accepts_run_label_and_eval_branch_names(tmp_path: Path) -> None:
    config = EvalConfig.model_validate(
        {
            "repo": {"path": tmp_path},
            "run": {
                "output_root": tmp_path / ".eval-feia" / "runs",
                "concurrency": 2,
                "label": "command eval",
            },
            "evals": [
                {
                    "id": "command-body-test",
                    "prompt": "Do a command body test.",
                    "branch_name": "eval/command-body-test",
                },
                {
                    "id": "attach-healthcheck",
                    "prompt": "Do an attach healthcheck.",
                    "branch_name": "eval/attach-healthcheck",
                },
            ],
        }
    )

    config = resolve_config_paths(config, tmp_path)

    assert config.run.candidates == 2
    assert config.run.label == "command eval"
    assert config.evals[0].branch_name == "eval/command-body-test"
    assert config.evals[1].branch_name == "eval/attach-healthcheck"


def test_eval_config_keeps_prompt_file_shape_working(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("legacy prompt\n", encoding="utf-8")

    config = EvalConfig.model_validate(
        {
            "repo": {"path": tmp_path},
            "run": {"candidates": 2, "concurrency": 1, "prompt_file": prompt},
        }
    )
    config = resolve_config_paths(config, tmp_path)

    assert config.evals == []
    assert config.run.candidates == 2
    assert config.run.prompt_file == prompt.resolve(strict=False)


def test_eval_item_rejects_prompt_and_prompt_file_together(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("hello", encoding="utf-8")

    with pytest.raises(ValueError, match="mutually exclusive"):
        EvalConfig.model_validate(
            {
                "run": {"prompt": "shared prompt"},
                "evals": [{"prompt": "hello inline", "prompt_file": prompt}],
            }
        )


def test_validation_command_name_must_be_single_path_segment() -> None:
    with pytest.raises(ValueError, match="single filename segment"):
        EvalConfig.model_validate(
            {
                "run": {"prompt": "shared prompt"},
                "validation": {"commands": [{"name": "../outside", "command": "pytest"}]},
            }
        )

    config = EvalConfig.model_validate(
        {
            "run": {"prompt": "shared prompt"},
            "validation": {"commands": [{"name": " unit-tests ", "command": "pytest"}]},
        }
    )

    assert config.validation.commands[0].name == "unit-tests"


def test_eval_item_rejects_per_candidate_label() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        EvalConfig.model_validate(
            {
                "run": {"prompt": "shared prompt"},
                "evals": [{"label": "not supported"}],
            }
        )


def test_candidate_spec_fallbacks_use_eval_id_then_index() -> None:
    config = EvalConfig.model_validate(
        {
            "run": {"prompt": "shared prompt", "candidates": 2},
            "evals": [
                {"id": "hello world", "prompt": "first prompt"},
                {"prompt": "second prompt"},
            ],
        }
    )

    specs = _build_candidate_specs(config, "run-abc123")

    assert specs[0].eval_id == "hello world"
    assert specs[0].branch_name == "eval/run-abc123/hello-world"
    assert specs[1].eval_id is None
    assert specs[1].branch_name == "eval/run-abc123/cand-002"


def test_candidate_spec_branch_fallbacks_ignore_labels() -> None:
    config = EvalConfig.model_validate(
        {
            "run": {"prompt": "shared prompt", "label": "run label"},
            "evals": [
                {"id": "explicit eval"},
                {},
            ],
        }
    )

    specs = _build_candidate_specs(config, "run-abc123")

    assert specs[0].eval_id == "explicit eval"
    assert specs[0].branch_name == "eval/run-abc123/explicit-eval"
    assert specs[1].eval_id is None
    assert specs[1].branch_name == "eval/run-abc123/cand-002"


def test_candidate_spec_run_label_is_not_candidate_metadata() -> None:
    config = EvalConfig.model_validate(
        {
            "run": {"prompt": "shared prompt", "candidates": 2, "label": "run label"},
        }
    )

    specs = _build_candidate_specs(config, "run-abc123")

    assert specs[0].eval_id is None
    assert specs[0].branch_name == "eval/run-abc123/cand-001"
    assert specs[1].eval_id is None
    assert specs[1].branch_name == "eval/run-abc123/cand-002"
