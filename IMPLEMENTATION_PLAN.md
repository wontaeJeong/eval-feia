# Implementation Plan

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Phase 0. Project bootstrap

Create Python package, `pyproject.toml`, Typer CLI, tests, and source layout.

## Phase 1. Core domain models

Define dataclasses or Pydantic models for:

- RunSpec
- BatchSpec
- RunState
- ServerInfo
- HealthCheck
- CwdCheck
- WorktreeInfo
- LiveSummary
- Metrics
- ValidationResult

## Phase 2. Worktree and manifest

Implement worktree manager and manifest writer.

Print worktree path immediately.

## Phase 3. OpenCode process manager

Implement version-pinned command builder and subprocess lifecycle.

## Phase 4. OpenCode HTTP client

Implement health, path, project, session, prompt, polling, and SSE methods.

## Phase 5. Runtime readiness

Add health check, cwd check, server info, and restart on mismatch.

## Phase 6. Live UX

Implement state store, Rich renderer, JSONL renderer, SSE parser, and polling merge.

## Phase 7. Metrics and validation

Compute trajectory metrics and validate output artifacts.

## Phase 8. Reports

Write JSON, CSV, JSONL, logs, and patch files.

## Phase 9. Tests

Add unit and fake-server integration tests.

## Phase 10. Hardening

Add cleanup, timeouts, redaction, docs, and examples.
