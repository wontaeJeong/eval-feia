# pyright: reportMissingImports=false
from __future__ import annotations

from pathlib import Path

from eval_feia.opencode_client import OpenCodeClient, compare_version, extract_cwd

from .conftest import FakeOpenCodeServer, FakeOpenCodeState


def test_compare_version() -> None:
    assert compare_version("1.4.6", "1.4.6") == "match"
    assert compare_version("1.4.6", "1.4.5") == "mismatch"
    assert compare_version("1.4.6", None) == "unknown"


def test_extract_cwd_success_and_ambiguity(tmp_path: Path) -> None:
    assert extract_cwd({"project": {"root": str(tmp_path)}}) == str(tmp_path.resolve())
    assert extract_cwd({"root": str(tmp_path), "path": "/different"}) is None


def test_health_and_cwd_from_path(tmp_path: Path) -> None:
    server = FakeOpenCodeServer(FakeOpenCodeState()).start()
    try:
        client = OpenCodeClient(server.url, "opencode", "pw", tmp_path)
        health = client.wait_health("1.4.6", 1, 0.01)
        cwd = client.verify_cwd(tmp_path)
        client.close()
    finally:
        server.stop()
    assert health.ok is True
    assert health.version_check == "match"
    assert cwd.cwd_check == "ok"


def test_cwd_fallback_to_project_current(tmp_path: Path) -> None:
    server = FakeOpenCodeServer(FakeOpenCodeState(path_empty=True)).start()
    try:
        client = OpenCodeClient(server.url, "opencode", "pw", tmp_path)
        cwd = client.verify_cwd(tmp_path)
        client.close()
    finally:
        server.stop()
    assert cwd.cwd_check == "ok"
    assert cwd.source == "project"


def test_cwd_mismatch_blocks_prompt_signal(tmp_path: Path) -> None:
    server = FakeOpenCodeServer(FakeOpenCodeState(cwd_modes=["wrong"])).start()
    try:
        client = OpenCodeClient(server.url, "opencode", "pw", tmp_path)
        cwd = client.verify_cwd(tmp_path)
        client.close()
    finally:
        server.stop()
    assert cwd.cwd_check == "mismatch"
