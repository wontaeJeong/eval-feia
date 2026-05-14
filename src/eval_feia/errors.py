from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ErrorRecord:
    kind: str
    message: str
    recoverable: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "recoverable": self.recoverable,
            "details": self.details,
        }


class EvalFeiaError(Exception):
    def __init__(
        self,
        kind: str,
        message: str,
        *,
        recoverable: bool = True,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.record = ErrorRecord(kind, message, recoverable, details or {})


class ConfigError(EvalFeiaError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("config_error", message, recoverable=False, details=details)


class HealthError(EvalFeiaError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("health_failed", message, recoverable=False, details=details)


class GitError(EvalFeiaError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("git_error", message, recoverable=False, details=details)


class CleanupSafetyError(EvalFeiaError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("cleanup_safety_failed", message, recoverable=False, details=details)
