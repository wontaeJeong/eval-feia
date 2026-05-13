from __future__ import annotations

import json
import importlib.util
import sys
import types
from pathlib import Path

from eval_feia.validation import validate_autogen_config

from .conftest import TEAM_CONFIG


def test_validation_passes_valid_team_config(tmp_path: Path) -> None:
    (tmp_path / "team.json").write_text(json.dumps(TEAM_CONFIG, ensure_ascii=False), encoding="utf-8")
    result = validate_autogen_config(tmp_path)
    assert result.validation_passed is True
    assert result.artifact_path == "team.json"


def test_validation_rejects_hardcoded_secret(tmp_path: Path) -> None:
    data = dict(TEAM_CONFIG)
    data["api_key"] = "sk-abcdefghijklmnopqrstuvwxyz"
    (tmp_path / "team.json").write_text(json.dumps(data), encoding="utf-8")
    result = validate_autogen_config(tmp_path)
    assert result.secret_scan_ok is False
    assert result.validation_passed is False


def test_validation_attempts_autogen_load_when_available(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "team.json").write_text(json.dumps(TEAM_CONFIG, ensure_ascii=False), encoding="utf-8")

    class FakeModel:
        @classmethod
        def model_validate(cls, config):
            return config

    class FakeLoader:
        called = False

        @classmethod
        def load_component(cls, _model):
            cls.called = True
            return object()

    fake_module = types.SimpleNamespace(ComponentModel=FakeModel, ComponentLoader=FakeLoader)
    monkeypatch.setitem(sys.modules, "autogen_core", fake_module)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name == "autogen_core" else None)
    result = validate_autogen_config(tmp_path)
    assert result.autogen_load_ok is True
    assert FakeLoader.called is True
    assert result.validation_passed is True


def test_validation_fails_when_autogen_load_fails(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "team.json").write_text(json.dumps(TEAM_CONFIG, ensure_ascii=False), encoding="utf-8")

    class FakeModel:
        @classmethod
        def model_validate(cls, config):
            return config

    class FakeLoader:
        @classmethod
        def load_component(cls, _model):
            raise ValueError("cannot load")

    class FakeComponent:
        @classmethod
        def load_component(cls, _config):
            raise ValueError("fallback failed")

    fake_module = types.SimpleNamespace(ComponentModel=FakeModel, ComponentLoader=FakeLoader, Component=FakeComponent)
    monkeypatch.setitem(sys.modules, "autogen_core", fake_module)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name == "autogen_core" else None)
    result = validate_autogen_config(tmp_path)
    assert result.autogen_load_ok is False
    assert result.validation_passed is False
    assert any("AutoGen load failed" in error for error in result.errors)
