from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import ConfigError


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = "http://127.0.0.1:4096"
    username: str | None = None
    password_env: str | None = None
    health_retries: int = Field(default=10, ge=1)
    health_interval_ms: int = Field(default=500, ge=0)

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
    prompt_file: Path
    agent: str | None = None
    model: ModelConfig | dict[str, Any] | None = None
    delete_sessions_after_collect: bool = False


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
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)

    @model_validator(mode="after")
    def validate_paths(self) -> "EvalConfig":
        if self.run.concurrency > self.run.candidates:
            self.run.concurrency = self.run.candidates
        return self


class ConfigOverrides(BaseModel):
    server_url: str | None = None
    repo: Path | None = None
    base_ref: str | None = None
    worktrees: int | None = None
    prompt_file: Path | None = None
    output_dir: Path | None = None


def load_config(config_path: Path | None, overrides: ConfigOverrides | None = None) -> EvalConfig:
    raw: Any
    base_dir = Path.cwd()
    if config_path is None:
        raw = {"run": {}}
    else:
        path = config_path.expanduser().resolve(strict=False)
        if not path.exists():
            raise ConfigError(f"config file does not exist: {path}")
        raw = _read_config_file(path)
        if not isinstance(raw, dict):
            raise ConfigError(f"config file must contain an object: {path}")

    raw = _apply_overrides(raw, overrides or ConfigOverrides())
    try:
        config = EvalConfig.model_validate(raw)
    except Exception as exc:  # pydantic includes detailed validation text
        raise ConfigError(f"invalid configuration: {exc}") from exc

    return resolve_config_paths(config, base_dir)


def _read_config_file(path: Path) -> Any:
    suffix = path.suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            with path.open("r", encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
        if suffix == ".json":
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        if suffix == ".toml":
            with path.open("rb") as fh:
                return tomllib.load(fh)
    except OSError as exc:
        raise ConfigError(f"failed to read config file {path}: {exc}") from exc
    except (json.JSONDecodeError, yaml.YAMLError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"failed to parse config file {path}: {exc}") from exc
    raise ConfigError(f"unsupported config format for {path}; use YAML, JSON, or TOML")


def _apply_overrides(raw: dict[str, Any], overrides: ConfigOverrides) -> dict[str, Any]:
    data = dict(raw)
    data.setdefault("server", {})
    data.setdefault("repo", {})
    data.setdefault("run", {})

    if overrides.server_url is not None:
        data["server"]["url"] = overrides.server_url
    if overrides.repo is not None:
        data["repo"]["path"] = overrides.repo
    if overrides.base_ref is not None:
        data["repo"]["base_ref"] = overrides.base_ref
    if overrides.worktrees is not None:
        data["run"]["candidates"] = overrides.worktrees
    if overrides.prompt_file is not None:
        data["run"]["prompt_file"] = overrides.prompt_file
    if overrides.output_dir is not None:
        data["run"]["output_root"] = overrides.output_dir
    return data


def resolve_config_paths(config: EvalConfig, base_dir: Path | None = None) -> EvalConfig:
    root = base_dir or Path.cwd()
    config.repo.path = _resolve_path(config.repo.path, root)
    config.repo.worktree_root = _resolve_path(config.repo.worktree_root, root)
    config.run.output_root = _resolve_path(config.run.output_root, root)
    config.run.prompt_file = _resolve_path(config.run.prompt_file, root)
    return config


def _resolve_path(path: Path, base_dir: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = base_dir / expanded
    return expanded.resolve(strict=False)


def read_prompt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"failed to read prompt file {path}: {exc}") from exc
