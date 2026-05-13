from __future__ import annotations

import os
import re
import secrets
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol


HOSTNAME = "127.0.0.1"
USERNAME = "opencode"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")


def validate_opencode_version(version: str) -> str:
    if not VERSION_RE.fullmatch(version):
        raise ValueError(f"opencode version must be an exact semver pin: {version}")
    return version


def build_opencode_command(version: str, port: int) -> list[str]:
    validate_opencode_version(version)
    return [
        "bunx",
        "-p",
        f"opencode-ai@{version}",
        "opencode",
        "serve",
        "--hostname",
        HOSTNAME,
        "--port",
        str(port),
    ]


def build_isolated_env(run_home: Path, run_tmp: Path, password: str | None = None) -> dict[str, str]:
    env = {key: os.environ[key] for key in ENV_ALLOWLIST if key in os.environ}
    actual_password = password or secrets.token_urlsafe(24)
    env.update(
        {
            "HOME": str(run_home),
            "XDG_CONFIG_HOME": str(run_home / ".config"),
            "XDG_CACHE_HOME": str(run_home / ".cache"),
            "TMPDIR": str(run_tmp),
            "OPENCODE_SERVER_USERNAME": USERNAME,
            "OPENCODE_SERVER_PASSWORD": actual_password,
        }
    )
    return env


def redacted_env_view(env: Mapping[str, str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key in ("HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "TMPDIR", "OPENCODE_SERVER_USERNAME"):
        if key in env:
            safe[key] = env[key]
    if "OPENCODE_SERVER_PASSWORD" in env:
        safe["OPENCODE_SERVER_PASSWORD"] = "<redacted>"
    return safe


@dataclass(slots=True)
class TerminationResult:
    terminated: bool
    killed: bool
    elapsed_ms: int


class ProcessLike(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...


@dataclass(slots=True)
class ProcessHandle:
    process: ProcessLike
    port: int
    hostname: str
    base_url: str
    password: str
    command: list[str]

    @property
    def pid(self) -> int:
        return self.process.pid

    def is_alive(self) -> bool:
        return self.process.poll() is None


class OpenCodeProcessManager:
    def __init__(self, version: str, hostname: str = HOSTNAME) -> None:
        self.version = version
        self.hostname = hostname

    def start(self, cwd: Path, run_home: Path, run_tmp: Path, port: int, log_path: Path | None = None) -> ProcessHandle:
        run_home.mkdir(parents=True, exist_ok=True)
        run_tmp.mkdir(parents=True, exist_ok=True)
        command = build_opencode_command(self.version, port)
        env = build_isolated_env(run_home, run_tmp)
        stdout_target = subprocess.DEVNULL
        log_file = None
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = log_path.open("a")
            stdout_target = log_file
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=stdout_target,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False,
            start_new_session=True,
        )
        if log_file is not None:
            log_file.close()
        return ProcessHandle(
            process=process,
            port=port,
            hostname=self.hostname,
            base_url=f"http://{self.hostname}:{port}",
            password=env["OPENCODE_SERVER_PASSWORD"],
            command=command,
        )

    def stop(self, handle: ProcessHandle, grace_seconds: float = 5.0) -> TerminationResult:
        return terminate_process_group(handle.process, grace_seconds=grace_seconds)


def terminate_process_group(process: ProcessLike, grace_seconds: float = 5.0) -> TerminationResult:
    started = time.monotonic()
    terminated = False
    killed = False
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            terminated = True
        except ProcessLookupError:
            terminated = True
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
                killed = True
            except ProcessLookupError:
                killed = True
            process.wait(timeout=grace_seconds)
    return TerminationResult(terminated=terminated, killed=killed, elapsed_ms=int((time.monotonic() - started) * 1000))
