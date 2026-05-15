from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import ConfigError


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = "http://127.0.0.1:4096"
    username: str | None = None
    password_env: str | None = None
    health_retries: int = Field(default=10, ge=1)
    health_interval_ms: int = Field(default=500, ge=0)
    health_timeout_seconds: float = Field(default=2.0, gt=0)

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("server.url must not include credentials, query, or fragment")
        return value

    def password(self) -> str | None:
        if not self.password_env:
            return None
        value = os.environ.get(self.password_env)
        if value is None:
            raise ConfigError(
                f"server.password_env references unset environment variable {self.password_env!r}"
            )
        return value


class RepoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Path = Path(".")
    base_ref: str = "HEAD"
    worktree_root: Path = Path(".eval-feia/worktrees")


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    providerID: str
    modelID: str


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_root: Path = Path(".eval-feia/runs")
    candidates: int = Field(default=1, ge=1)
    concurrency: int = Field(default=1, ge=1)
    timeout_seconds: float = Field(default=3600.0, gt=0)
    prompt: str | None = None
    prompt_file: Path | None = None
    label: str | None = None
    agent: str | None = None
    model: ModelConfig | dict[str, Any] | None = None
    command: str | None = None
    delete_sessions_after_collect: bool = False

    @model_validator(mode="after")
    def validate_prompt_source(self) -> "RunConfig":
        if self.prompt is not None and self.prompt_file is not None:
            raise ValueError(
                "run.prompt and run.prompt_file are mutually exclusive; provide only one"
            )
        return self


class EvalItemConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    prompt: str | None = None
    prompt_file: Path | None = None
    branch_name: str | None = None

    @model_validator(mode="after")
    def validate_prompt_source(self) -> "EvalItemConfig":
        if self.prompt is not None and self.prompt_file is not None:
            raise ValueError(
                "eval prompt and prompt_file are mutually exclusive; provide only one"
            )
        return self


class ValidationCommandConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    command: str
    timeout_seconds: float = Field(default=600.0, gt=0)
    required: bool = True

    @field_validator("name")
    @classmethod
    def non_empty_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("validation command name must not be empty")
        return value


class ValidationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commands: list[ValidationCommandConfig] = Field(default_factory=list)


class SummaryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_full_diff: bool = False
    include_messages: bool = True
    include_child_sessions: bool = True


class EvalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: ServerConfig = Field(default_factory=ServerConfig)
    repo: RepoConfig = Field(default_factory=RepoConfig)
    run: RunConfig
    evals: list[EvalItemConfig] = Field(default_factory=list)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)

    @model_validator(mode="after")
    def validate_evals_and_concurrency(self) -> "EvalConfig":
        if self.evals:
            self.run.candidates = len(self.evals)
        if self.run.prompt is None and self.run.prompt_file is None:
            missing_prompt = [
                index
                for index, item in enumerate(self.evals, start=1)
                if item.prompt is None and item.prompt_file is None
            ]
            if missing_prompt:
                raise ValueError(
                    "run.prompt_file, run.prompt, or an eval-specific prompt/prompt_file is required"
                )
            if not self.evals:
                raise ValueError("run.prompt_file or run.prompt is required")
        if self.run.concurrency > self.run.candidates:
            self.run.concurrency = self.run.candidates
        return self


def build_config(
    *,
    server_url: str | None = None,
    repo: Path | None = None,
    base_ref: str | None = None,
    candidates: int | None = None,
    prompt: str | None = None,
    prompt_file: Path | None = None,
    label: str | None = None,
    command: str | None = None,
    output_dir: Path | None = None,
    base_dir: Path | None = None,
) -> EvalConfig:
    raw: dict[str, Any] = {"run": {}}
    _set_nested(raw, "server", "url", server_url)
    _set_nested(raw, "repo", "path", repo)
    _set_nested(raw, "repo", "base_ref", base_ref)
    _set_nested(raw, "run", "candidates", candidates)
    _set_nested(raw, "run", "prompt", prompt)
    _set_nested(raw, "run", "prompt_file", prompt_file)
    _set_nested(raw, "run", "label", label)
    _set_nested(raw, "run", "command", command)
    _set_nested(raw, "run", "output_root", output_dir)
    try:
        config = EvalConfig.model_validate(raw)
    except Exception as exc:  # pydantic includes detailed validation text
        raise ConfigError(f"invalid configuration: {exc}") from exc
    return resolve_config_paths(config, base_dir)


def _set_nested(data: dict[str, Any], section: str, key: str, value: Any | None) -> None:
    if value is not None:
        data.setdefault(section, {})[key] = value


def resolve_config_paths(config: EvalConfig, base_dir: Path | None = None) -> EvalConfig:
    root = base_dir or Path.cwd()
    config.repo.path = _resolve_path(config.repo.path, root)
    config.repo.worktree_root = _resolve_path(config.repo.worktree_root, root)
    config.run.output_root = _resolve_path(config.run.output_root, root)
    if config.run.prompt_file is not None:
        config.run.prompt_file = _resolve_path(config.run.prompt_file, root)
    for item in config.evals:
        if item.prompt_file is not None:
            item.prompt_file = _resolve_path(item.prompt_file, root)
    return config


def _resolve_path(path: Path, base_dir: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = base_dir / expanded
    return expanded.resolve(strict=False)


def read_prompt(prompt: str | None, prompt_file: Path | None) -> str:
    if prompt is not None:
        return prompt
    if prompt_file is None:
        raise ConfigError("run.prompt or run.prompt_file is required")
    try:
        return prompt_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"failed to read prompt file {prompt_file}: {exc}") from exc
