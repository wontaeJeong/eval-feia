from __future__ import annotations

import os
import secrets
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .models import LOOPBACK_HOST


def build_opencode_command(version: str, port: int, hostname: str = LOOPBACK_HOST) -> list[str]:
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


@dataclass
class TerminationResult:
    terminated: bool
    killed: bool
    elapsed_ms: int


class ServerProcess(Protocol):
    @property
    def pid(self) -> int: ...

    @property
    def port(self) -> int: ...

    @property
    def hostname(self) -> str: ...

    @property
    def base_url(self) -> str: ...

    @property
    def username(self) -> str: ...

    @property
    def password(self) -> str | None: ...

    def is_alive(self) -> bool: ...

    def stop(self, grace_seconds: float = 5.0) -> TerminationResult: ...


@dataclass
class ManagedServerProcess:
    popen: subprocess.Popen[bytes]
    port: int
    hostname: str
    username: str
    password: str

    @property
    def pid(self) -> int:
        return self.popen.pid

    @property
    def base_url(self) -> str:
        return f"http://{self.hostname}:{self.port}"

    def is_alive(self) -> bool:
        return self.popen.poll() is None

    def stop(self, grace_seconds: float = 5.0) -> TerminationResult:
        start = time.monotonic()
        terminated = False
        killed = False
        if self.popen.poll() is not None:
            return TerminationResult(True, False, int((time.monotonic() - start) * 1000))
        try:
            os.killpg(os.getpgid(self.popen.pid), signal.SIGTERM)
            terminated = True
        except ProcessLookupError:
            return TerminationResult(True, False, int((time.monotonic() - start) * 1000))
        except OSError:
            self.popen.terminate()
            terminated = True
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline:
            if self.popen.poll() is not None:
                return TerminationResult(terminated, killed, int((time.monotonic() - start) * 1000))
            time.sleep(0.05)
        if self.popen.poll() is None:
            try:
                os.killpg(os.getpgid(self.popen.pid), signal.SIGKILL)
                killed = True
            except ProcessLookupError:
                pass
            except OSError:
                self.popen.kill()
                killed = True
        return TerminationResult(terminated, killed, int((time.monotonic() - start) * 1000))


class OpenCodeProcessManager:
    def start(
        self,
        *,
        cwd: Path,
        run_home: Path,
        run_tmp: Path,
        port: int,
        version: str,
        log_path: Path,
        hostname: str = LOOPBACK_HOST,
    ) -> ManagedServerProcess:
        run_home.mkdir(parents=True, exist_ok=True)
        run_tmp.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        password = secrets.token_urlsafe(24)
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(run_home),
                "XDG_CONFIG_HOME": str(run_home / ".config"),
                "XDG_CACHE_HOME": str(run_home / ".cache"),
                "TMPDIR": str(run_tmp),
                "OPENCODE_SERVER_USERNAME": "opencode",
                "OPENCODE_SERVER_PASSWORD": password,
            }
        )
        command = build_opencode_command(version, port, hostname)
        log_file = log_path.open("ab")
        popen = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return ManagedServerProcess(popen=popen, port=port, hostname=hostname, username="opencode", password=password)


@dataclass
class ExternalServerProcess:
    base_url: str
    port: int
    hostname: str = LOOPBACK_HOST
    username: str = "opencode"
    password: str | None = None
    pid: int = os.getpid()
    stopped: bool = False

    def is_alive(self) -> bool:
        return not self.stopped

    def stop(self, grace_seconds: float = 5.0) -> TerminationResult:
        self.stopped = True
        return TerminationResult(True, False, 0)


class ExternalServerProcessManager:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.starts = 0
        self.stops = 0

    def start(
        self,
        *,
        cwd: Path,
        run_home: Path,
        run_tmp: Path,
        port: int,
        version: str,
        log_path: Path,
        hostname: str = LOOPBACK_HOST,
    ) -> ExternalServerProcess:
        self.starts += 1
        return ExternalServerProcess(base_url=self.base_url, port=port, hostname=hostname, pid=os.getpid())
