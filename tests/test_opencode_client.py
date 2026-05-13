from __future__ import annotations

from pathlib import Path

from eval_feia.opencode_client import OpenCodeClient, check_version, extract_path

from .conftest import FakeOpenCodeServer


def test_health_success(fake_server: FakeOpenCodeServer) -> None:
    client = OpenCodeClient(fake_server.url, password="pw")
    try:
        health = client.poll_health(1, 0.01)
    finally:
        client.close()
    assert health.ok is True
    assert health.version == "1.4.6"


def test_health_timeout(tmp_path: Path) -> None:
    server = FakeOpenCodeServer(str(tmp_path), healthy=False).start()
    client = OpenCodeClient(server.url, password="pw")
    try:
        health = client.poll_health(0.03, 0.01)
    finally:
        client.close()
        server.stop()
    assert health.ok is False


def test_cwd_success_from_path(tmp_path: Path) -> None:
    server = FakeOpenCodeServer(str(tmp_path)).start()
    client = OpenCodeClient(server.url, password="pw")
    try:
        result = client.verify_cwd(tmp_path)
    finally:
        client.close()
        server.stop()
    assert result.result == "ok"
    assert result.source == "/path"


def test_cwd_success_from_project_fallback(tmp_path: Path) -> None:
    server = FakeOpenCodeServer(str(tmp_path), path_returns_empty=True).start()
    client = OpenCodeClient(server.url, password="pw")
    try:
        result = client.verify_cwd(tmp_path)
    finally:
        client.close()
        server.stop()
    assert result.result == "ok"
    assert result.source == "/project/current"


def test_cwd_mismatch(tmp_path: Path) -> None:
    server = FakeOpenCodeServer(str(tmp_path / "actual")).start()
    client = OpenCodeClient(server.url, password="pw")
    try:
        result = client.verify_cwd(tmp_path / "expected")
    finally:
        client.close()
        server.stop()
    assert result.result == "mismatch"


def test_cwd_unknown_when_path_cannot_be_proven(tmp_path: Path) -> None:
    server = FakeOpenCodeServer(str(tmp_path), path_returns_empty=True, project_returns_empty=True).start()
    client = OpenCodeClient(server.url, password="pw")
    try:
        result = client.verify_cwd(tmp_path)
    finally:
        client.close()
        server.stop()
    assert result.result == "unknown"


def test_extract_path_ignores_arbitrary_strings() -> None:
    assert extract_path({"status": "ok"}) is None
    assert extract_path({"data": {"cwd": "/tmp/example"}}) == "/tmp/example"


def test_version_check_values() -> None:
    assert check_version("1.4.6", "1.4.6") == "match"
    assert check_version("1.4.6", "1.4.5") == "mismatch"
    assert check_version("1.4.6", None) == "unknown"
