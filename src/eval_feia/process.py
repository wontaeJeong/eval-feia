from __future__ import annotations

import os
import re
import secrets
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


HOSTNAME = "127.0.0.1"
USERNAME = "opencode"
SAFE_ENV_KEYS = {
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
    "BUN_INSTALL",
}
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def validate_opencode_version(version: str) -> str:
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("opencode version must be an exact semver, for example 1.4.6")
    return version


def build_opencode_command(version: str, port: int, hostname: str = HOSTNAME) -> list[str]:
    version = validate_opencode_version(version)
    return [
        "bunx",
        "-p",
        f"opencode-ai@{version}",
        "opencode",
        "serve",
        "--hostname",
        hostname,
        "--port",
        str(port),
    ]


@dataclass(slots=True)
class ServerProcess:
    process: subprocess.Popen[bytes]
    password: str
    log_path: Path

    @property
    def pid(self) -> int:
        return self.process.pid

    @property
    def returncode(self) -> int | None:
        return self.process.poll()

    def is_alive(self) -> bool:
        return self.process.poll() is None


class ProcessManager:
    def build_command(self, version: str, port: int, hostname: str = HOSTNAME) -> list[str]:
        return build_opencode_command(version, port, hostname)

    def make_env(self, home: Path, tmp: Path, password: str | None = None) -> tuple[dict[str, str], str]:
        token = password or secrets.token_urlsafe(24)
        env = {key: value for key, value in os.environ.items() if key in SAFE_ENV_KEYS}
        env.update(
            {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_CACHE_HOME": str(home / ".cache"),
                "TMPDIR": str(tmp),
                "OPENCODE_SERVER_USERNAME": USERNAME,
                "OPENCODE_SERVER_PASSWORD": token,
            }
        )
        return env, token

    def start(self, *, worktree: Path, home: Path, tmp: Path, log_path: Path, version: str, port: int) -> ServerProcess:
        home.mkdir(parents=True, exist_ok=True)
        (home / ".config").mkdir(parents=True, exist_ok=True)
        (home / ".cache").mkdir(parents=True, exist_ok=True)
        tmp.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env, password = self.make_env(home, tmp)
        log_file = log_path.open("ab")
        process = subprocess.Popen(
            self.build_command(version, port),
            cwd=worktree,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return ServerProcess(process=process, password=password, log_path=log_path)

    def stop(self, server: ServerProcess, grace_seconds: float = 3.0) -> dict[str, object]:
        pid = server.pid
        terminated = False
        killed = False
        if server.returncode is not None:
            return {"pid": pid, "terminated": False, "killed": False, "returncode": server.returncode}
        try:
            os.killpg(pid, signal.SIGTERM)
            terminated = True
        except ProcessLookupError:
            return {"pid": pid, "terminated": False, "killed": False, "returncode": server.returncode}
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline:
            if server.returncode is not None:
                return {"pid": pid, "terminated": terminated, "killed": killed, "returncode": server.returncode}
            time.sleep(0.05)
        if server.returncode is None:
            try:
                os.killpg(pid, signal.SIGKILL)
                killed = True
            except ProcessLookupError:
                pass
        try:
            server.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        return {"pid": pid, "terminated": terminated, "killed": killed, "returncode": server.returncode}
