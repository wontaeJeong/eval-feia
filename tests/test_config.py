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


def test_eval_config_accepts_eval_branch_name_and_label(tmp_path: Path) -> None:
    config = EvalConfig.model_validate(
        {
            "repo": {"path": tmp_path},
            "run": {"output_root": tmp_path / ".eval-feia" / "runs", "concurrency": 2},
            "evals": [
                {
                    "id": "command-body-test",
                    "prompt": "Do a command body test.",
                    "branch_name": "eval/command-body-test",
                    "label": "command body test",
                },
                {
                    "id": "attach-healthcheck",
                    "prompt": "Do an attach healthcheck.",
                    "branch_name": "eval/attach-healthcheck",
                    "label": "attach healthcheck",
                },
            ],
        }
    )

    config = resolve_config_paths(config, tmp_path)

    assert config.run.candidates == 2
    assert config.evals[0].branch_name == "eval/command-body-test"
    assert config.evals[0].label == "command body test"
    assert config.evals[1].branch_name == "eval/attach-healthcheck"
    assert config.evals[1].label == "attach healthcheck"


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

    specs = _build_candidate_specs(config)

    assert specs[0].eval_id == "hello world"
    assert specs[0].label == "hello world"
    assert specs[0].branch_name == "eval/hello-world"
    assert specs[1].eval_id == "cand-002"
    assert specs[1].label == "cand-002"
    assert specs[1].branch_name == "eval/cand-002"


def test_candidate_spec_label_and_branch_fallback_do_not_let_run_label_override_eval_id() -> None:
    config = EvalConfig.model_validate(
        {
            "run": {"prompt": "shared prompt", "label": "run label"},
            "evals": [
                {"id": "explicit eval"},
                {"label": "Label Only"},
            ],
        }
    )

    specs = _build_candidate_specs(config)

    assert specs[0].label == "explicit eval"
    assert specs[0].branch_name == "eval/explicit-eval"
    assert specs[1].label == "Label Only"
    assert specs[1].branch_name == "eval/Label-Only"
