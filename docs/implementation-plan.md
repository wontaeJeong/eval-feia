# Implementation Plan

This document records the implemented MVP shape after the `init-v3`, `list`, and progress-logging work was integrated.

## Phase 0: Repository bootstrap

Implemented Python project structure:

```text
pyproject.toml
README.md
AGENTS.md
src/eval_feia/
tests/
examples/
```

Runtime dependencies remain:

```toml
dependencies = [
  "typer>=0.12",
  "httpx>=0.27",
  "pydantic>=2",
  "rich>=13"
]
```

## Phase 1: Runtime models and manifest

Implemented typed runtime configuration, manifest schemas, path resolution, generated branch/worktree metadata, run labels, and JSON serialization.

## Phase 2: Opencode REST client

Implemented `opencode_client.py` for health, path/project preflight, session creation, synchronous message and command sends, aborts, event streaming, session/message/children/todo/diff collection, and file status.

Client invariant:

- GET/HEAD calls use `directory` query.
- Non-GET calls use `x-opencode-directory` header.
- Directory value is absolute and URL-encoded exactly once.

## Phase 3: Git worktree manager

Implemented base SHA resolution, run-scoped branch creation, compact worktree paths, worktree removal, and local git status/diff collection.

## Phase 4: Runner

Implemented `run` orchestration:

- creates durable stored result records
- preflights the external opencode server
- creates run artifact directories and worktrees
- executes candidates sequentially through REST
- streams opencode progress events filtered by session ID
- collects opencode and local artifacts
- runs validation commands
- writes summaries
- prints plain final output

## Phase 5: Listing and results

Implemented:

- read-only `result list` for generated run artifacts and stored result metadata
- file-backed `result list` filters for status, branch, and label
- read-only `result show`, `result path`, and `result file` for durable stored result inspection

## Phase 6: Clean command

Implemented manifest-based cleanup with dry-run, force handling, and stored-results cleanup through `clean --results`.

## Phase 7: Tests

Implemented unit tests and fake-server integration tests covering request shapes, directory context, run orchestration, progress logging, collection, cleanup safety, stored results, generated run IDs, saved-run listing, and CLI help/output behavior.

## Phase 8: Documentation and examples

Documentation now covers the REST/SSE execution contract, direct CLI flags, command mode, generated artifacts, durable stored results, explicit artifact/result/cleanup commands, safety rules, and manual smoke testing.

## MVP completion checklist

- [x] `eval-feia run --prompt-file examples/prompt.md --repo .` works against the fake server path covered by tests.
- [x] Health check retry works.
- [x] Worktree paths are printed.
- [x] Session creation uses correct directory context.
- [x] Prompt uses REST `/session/{id}/message`, or `/session/{id}/command` when command mode is configured.
- [x] Results are collected and summarized automatically.
- [x] Stored result history is written and inspectable.
- [x] File-backed filtered listing works.
- [x] `list` inspects generated run artifacts and stored result metadata read-only.
- [x] `clean --dry-run`, `clean`, and `clean --results` are safety-gated.
- [x] Tests cover request context, cleanup safety, stored results, saved run listing, progress logging, and final summary generation.
