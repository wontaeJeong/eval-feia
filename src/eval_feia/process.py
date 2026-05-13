from __future__ import annotations

import os
import secrets
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HOSTNAME = "127.0.0.1"
USERNAME = "opencode"


def build_opencode_command(version: str, port: int, hostname: str = HOSTNAME) -> list[str]:
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


def allocate_ports(base_port: int, count: int) -> list[int]:
    return [base_port + offset for offset in range(count)]


def generate_password() -> str:
    return secrets.token_urlsafe(24)


def build_server_env(
    run_home: Path,
    run_tmp: Path,
    password: str,
    base_env: dict[str, str] | None = None,
    username: str = USERNAME,
) -> dict[str, str]:
    env = dict(base_env or os.environ)
    env.update(
        {
            "HOME": str(run_home),
            "XDG_CONFIG_HOME": str(run_home / ".config"),
            "XDG_CACHE_HOME": str(run_home / ".cache"),
            "TMPDIR": str(run_tmp),
            "OPENCODE_SERVER_USERNAME": username,
            "OPENCODE_SERVER_PASSWORD": password,
        }
    )
    return env


@dataclass(slots=True)
class ProcessHandle:
    process: subprocess.Popen[str] | None
    pid: int
    port: int
    base_url: str
    command: list[str]
    log_file: Any | None = None

    def alive(self) -> bool:
        return self.process is None or self.process.poll() is None


def terminate_process_group(proc: subprocess.Popen[str], timeout: float = 5.0) -> dict[str, bool]:
    terminated = False
    killed = False
    if proc.poll() is not None:
        return {"terminated": True, "killed": False}
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
        terminated = True
    except ProcessLookupError:
        return {"terminated": True, "killed": False}
    except OSError:
        proc.terminate()
        terminated = True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return {"terminated": terminated, "killed": killed}
        time.sleep(0.05)
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL)
        killed = True
    except ProcessLookupError:
        pass
    except OSError:
        proc.kill()
        killed = True
    return {"terminated": terminated, "killed": killed}


class OpenCodeProcessManager:
    def start(
        self,
        command: list[str],
        cwd: Path,
        env: dict[str, str],
        log_path: Path,
        port: int,
    ) -> ProcessHandle:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("a", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
        except Exception:
            log_file.close()
            raise
        return ProcessHandle(
            process=proc,
            pid=proc.pid,
            port=port,
            base_url=f"http://{HOSTNAME}:{port}",
            command=command,
            log_file=log_file,
        )

    def stop(self, handle: ProcessHandle, timeout: float = 5.0) -> dict[str, bool]:
        result = {"terminated": True, "killed": False}
        if handle.process is not None:
            result = terminate_process_group(handle.process, timeout=timeout)
        if handle.log_file is not None:
            handle.log_file.close()
            handle.log_file = None
        return result
