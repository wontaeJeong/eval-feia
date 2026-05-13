# Architecture Decisions

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## ADR-001: Use Python and Typer

Decision: Use Python with Typer for CLI.

Reason: Fast implementation, testability, good CLI UX, and strong ecosystem.

## ADR-002: Use per-run Git worktrees

Decision: Use temporary detached worktrees.

Reason: Isolation and reproducibility.

## ADR-003: Local logs are source of truth

Decision: Local JSONL and JSON files are canonical.

Reason: Remote instrumentation may fail or be partial.

## ADR-004: Restart on served-state mismatch

Decision: Restart if version or cwd mismatches.

Reason: Evaluation results are invalid if runtime state is wrong.

## ADR-005: SSE before prompt

Decision: Connect SSE before prompt submission.

Reason: Prevent missing early events.

## ADR-006: Prompt async preferred

Decision: Use `/session/:id/prompt_async`.

Reason: Avoid blocking live UX.
