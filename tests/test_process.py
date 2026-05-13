from __future__ import annotations

from pathlib import Path

import os

import pytest

from eval_feia.process import ProcessManager, build_opencode_command, validate_opencode_version


def test_command_builder_uses_version_pinned_bunx() -> None:
    command = build_opencode_command("1.4.6", 4567)
    assert command == ["bunx", "-p", "opencode-ai@1.4.6", "opencode", "serve", "--hostname", "127.0.0.1", "--port", "4567"]
    assert command[0] != "opencode"


def test_process_environment_sets_password_and_isolation(tmp_path: Path) -> None:
    env, password = ProcessManager().make_env(tmp_path / "home", tmp_path / "tmp", password="secret-token")
    assert password == "secret-token"
    assert env["OPENCODE_SERVER_PASSWORD"] == "secret-token"
    assert env["OPENCODE_SERVER_USERNAME"] == "opencode"
    assert env["HOME"] == str(tmp_path / "home")
    assert env["TMPDIR"] == str(tmp_path / "tmp")


def test_process_environment_does_not_inherit_secret(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "do-not-copy")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    env, _password = ProcessManager().make_env(tmp_path / "home", tmp_path / "tmp", password="secret-token")
    assert "GITHUB_TOKEN" not in env
    assert "PATH" in env


def test_opencode_version_requires_exact_semver() -> None:
    assert validate_opencode_version("1.4.6") == "1.4.6"
    with pytest.raises(ValueError):
        validate_opencode_version("latest")
