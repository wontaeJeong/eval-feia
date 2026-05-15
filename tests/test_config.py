from __future__ import annotations

from pathlib import Path

from eval_feia.config import EvalConfig, load_config
from eval_feia.runner import _build_candidate_specs


def test_load_config_parses_eval_branch_name_and_label(tmp_path: Path) -> None:
    config_path = tmp_path / "eval-feia.yaml"
    config_path.write_text(
        f"""
repo:
  path: "{tmp_path}"
run:
  output_root: "{tmp_path / '.eval-feia' / 'runs'}"
  concurrency: 2
evals:
  - id: command-body-test
    prompt: "Do a command body test."
    branch_name: "eval/command-body-test"
    label: "command body test"
  - id: attach-healthcheck
    prompt: "Do an attach healthcheck."
    branch_name: "eval/attach-healthcheck"
    label: "attach healthcheck"
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.run.candidates == 2
    assert config.evals[0].branch_name == "eval/command-body-test"
    assert config.evals[0].label == "command body test"
    assert config.evals[1].branch_name == "eval/attach-healthcheck"
    assert config.evals[1].label == "attach healthcheck"


def test_load_config_keeps_existing_prompt_file_shape_working(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("legacy prompt\n", encoding="utf-8")
    config_path = tmp_path / "eval-feia.json"
    config_path.write_text(
        f"""
{{
  "repo": {{"path": "{tmp_path}"}},
  "run": {{
    "candidates": 2,
    "concurrency": 1,
    "prompt_file": "{prompt}"
  }}
}}
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.evals == []
    assert config.run.candidates == 2
    assert config.run.prompt_file == prompt.resolve(strict=False)


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
