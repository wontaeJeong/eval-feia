# Implementation Plan

This document records the implemented MVP shape after the `init-v3`, `db`, and `list` branch work was integrated.

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

Implemented typed runtime configuration, manifest schemas, path resolution, generated branch/worktree metadata, run labels, and JSON serialization. Manifests now include the default SQLite DB path when that DB is owned by the generated output root.

## Phase 2: Opencode REST client

Implemented `opencode_client.py` for health, path/project preflight, session creation, synchronous message and command sends, aborts, session/message/children/todo/diff collection, and file status.

Client invariant:

- GET/HEAD calls use `directory` query.
- Non-GET calls use `x-opencode-directory` header.
- Directory value is absolute and URL-encoded exactly once.

## Phase 3: Git worktree manager

Implemented base SHA resolution, run-scoped branch creation, compact worktree paths, worktree removal, and local git status/diff collection.

## Phase 4: Runner

Implemented `run` orchestration:

- creates durable stored result records
- records SQLite run metadata and lifecycle events
- preflights the external opencode server
- creates run artifact directories and worktrees
- executes candidates sequentially through REST
- collects opencode and local artifacts
- runs validation commands
- writes summaries
- prints plain final output

## Phase 5: Listing, results, and indexing

Implemented:

- read-only `list` for generated run artifacts
- SQLite-backed `list` when `EVAL_FEIA_DB_PATH` or index filters are used
- idempotent SQLite backfill from existing file outputs
- read-only `results list`, `results show`, `results path`, and `results file` for durable stored result history

## Phase 6: Clean command

Implemented manifest-based cleanup with dry-run, force handling, stored-results cleanup through `clean --results`, SQLite output-missing marking, and default DB deletion only through manifest-validated `clean --delete-index`.

## Phase 7: Tests

Implemented unit tests and fake-server integration tests covering request shapes, directory context, run orchestration, collection, cleanup safety, stored results, generated run IDs, saved-run listing, SQLite indexing, and CLI help/output behavior.

## Phase 8: Documentation and examples

Documentation now covers the REST-only execution contract, direct CLI flags, command mode, generated artifacts, durable stored results, SQLite metadata index, explicit artifact/result/cleanup commands, safety rules, and manual smoke testing.

## MVP completion checklist

- [x] `eval-feia run --prompt-file examples/prompt.md --repo .` works against the fake server path covered by tests.
- [x] Health check retry works.
- [x] Worktree paths are printed.
- [x] Session creation uses correct directory context.
- [x] Prompt uses REST `/session/{id}/message`, or `/session/{id}/command` when command mode is configured.
- [x] Results are collected and summarized automatically.
- [x] Stored result history is written and inspectable.
- [x] SQLite metadata indexing and filtered listing work.
- [x] `list` inspects generated run artifacts read-only.
- [x] `clean --dry-run`, `clean`, `clean --results`, and `clean --delete-index` are safety-gated.
- [x] Tests cover request context, cleanup safety, stored results, SQLite index behavior, saved run listing, and final summary generation.
