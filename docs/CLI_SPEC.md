# CLI Specification

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## CLI library

Use Typer.

Use Rich for display.

## Commands

### run

Runs a new evaluation batch.

Example:

```bash
uv run eval-feia run --repo . --count 20 --concurrency 2 --opencode-version 1.4.6
```

### collect

Collects local artifacts and recomputes summaries.

### fetch

Fetches remote instrumentation metrics.

### cleanup

Removes manifest-owned temp resources.

### inspect

Displays a run or batch summary.

## run options

```text
--repo PATH
--count INTEGER
--concurrency INTEGER
--prompt TEXT
--prompt-file PATH
--skill TEXT
--branch TEXT
--worktree-root PATH
--output-dir PATH
--base-port INTEGER
--opencode-version TEXT
--provider TEXT
--model TEXT
--server-start-timeout-seconds INTEGER
--health-poll-interval-seconds FLOAT
--cwd-check / --no-cwd-check
--restart-on-mismatch / --no-restart-on-mismatch
--max-server-restarts INTEGER
--idle-quiet-seconds INTEGER
--hard-timeout-seconds INTEGER
--no-live
--json
```

## UX rules

- Print worktree path immediately after creation.
- Print served server info after readiness checks.
- Print restart events when mismatch occurs.
- Show live trajectory while running.
- Keep table cells short.
- Store long details in JSON/logs.

## JSON mode

`--json` mode outputs JSONL only.

It must be parseable.

Do not mix Rich output with JSONL.

## Exit codes

- `0`: command succeeded
- `1`: one or more runs failed
- `2`: invalid CLI usage
- `3`: runtime guard failure
- `4`: cleanup failure


## Additional requirement: worktree path output

When a worktree is created, the CLI must immediately output the resolved worktree path.

Human output example:

```text
[run-001] worktree: /tmp/eval-feia/batch-20260513/run-001/worktree
```

JSONL output example:

```json
{"type":"worktree_created","run_id":"run-001","path":"/tmp/eval-feia/batch-20260513/run-001/worktree","commit":"abc123"}
```
