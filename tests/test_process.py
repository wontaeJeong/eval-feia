# pyright: reportMissingImports=false
from pathlib import Path

from eval_feia.process import allocate_ports, build_opencode_command, build_server_env


def test_command_builder_uses_pinned_bunx() -> None:
    command = build_opencode_command("1.4.6", 4567)
    assert command == ["bunx", "-p", "opencode-ai@1.4.6", "opencode", "serve", "--hostname", "127.0.0.1", "--port", "4567"]
    assert command[0] != "opencode"


def test_port_allocation_avoids_collisions() -> None:
    assert allocate_ports(4096, 3) == [4096, 4097, 4098]
    assert len(set(allocate_ports(5000, 20))) == 20


def test_server_env_sets_password_without_dropping_isolation(tmp_path: Path) -> None:
    env = build_server_env(tmp_path / "home", tmp_path / "tmp", "secret", base_env={"PATH": "/bin"})
    assert env["OPENCODE_SERVER_USERNAME"] == "opencode"
    assert env["OPENCODE_SERVER_PASSWORD"] == "secret"
    assert env["HOME"] == str(tmp_path / "home")
    assert env["TMPDIR"] == str(tmp_path / "tmp")
