# MASTER IMPLEMENTATION PROMPT: eval-feia from Zero

You are implementing eval-feia from zero.

Do not assume an existing implementation. Build a small but complete Python CLI application using Typer, Rich, pytest, and a thin OpenCode HTTP integration layer.

Before coding, read the documentation files from the docs package.

## Objective

Implement `eval-feia`, an OpenCode Agent Evaluation Harness.

The app must benchmark agent trajectories and outputs by running the same task through version-pinned OpenCode server instances in isolated Git worktrees.

## Required behavior

1. Create one temporary Git worktree per run.
2. Print the worktree path immediately after creation.
3. Start one `opencode serve` instance per run.
4. Launch OpenCode only through a version-pinned command equivalent to:

```bash
bunx -p opencode-ai@<version> opencode serve --hostname 127.0.0.1 --port <port>
```

5. Set `OPENCODE_SERVER_PASSWORD`.
6. Poll `/global/health` until healthy.
7. Verify actual served cwd using `/path`, then `/project/current` as fallback.
8. Print actual served server info after readiness.
9. If version or cwd mismatches, kill the server process group and restart it.
10. Do not send prompt to a mismatched or unhealthy server.
11. Create an OpenCode session.
12. Connect SSE before sending prompt.
13. Send prompt through async prompt endpoint when available.
14. Show live trajectory state in Rich mode.
15. Output progress JSONL in `--json` mode.
16. Poll status, children, and todo while running.
17. Detect idle completion across parent and child sessions.
18. Write JSON, CSV, JSONL, logs, and validation artifacts.
19. Validate the generated AutoGen Teams config.
20. Provide unit tests and fake OpenCode server integration tests.

## Required package layout

```text
src/eval_feia/
  __init__.py
  cli.py
  models.py
  orchestrator.py
  worktree.py
  process.py
  opencode_client.py
  sse.py
  live.py
  metrics.py
  validation.py
  reports.py
  cleanup.py
tests/
```

## CLI commands

Implement:

```text
eval-feia run
eval-feia collect
eval-feia fetch
eval-feia cleanup
eval-feia inspect
```

## Required options for run

```text
--repo
--count / -n
--concurrency / -j
--prompt / -P
--prompt-file
--skill / -s
--branch / -b
--worktree-root
--output-dir
--base-port
--opencode-version
--provider
--model
--server-start-timeout-seconds
--health-poll-interval-seconds
--cwd-check / --no-cwd-check
--restart-on-mismatch / --no-restart-on-mismatch
--max-server-restarts
--idle-quiet-seconds
--hard-timeout-seconds
--no-live
--json
```

## Critical gating

Prompt submission requires:

```text
worktree created
server process alive
health ok
server info emitted
version_check != mismatch
cwd_check != mismatch
session created
SSE connected
```

## Output files

Write:

```text
results/<batch_id>/manifest.json
results/<batch_id>/summary.json
results/<batch_id>/summary.csv
results/<batch_id>/runs/<run_id>/run.json
results/<batch_id>/runs/<run_id>/events.jsonl
results/<batch_id>/runs/<run_id>/status_snapshots.jsonl
results/<batch_id>/runs/<run_id>/children_snapshots.jsonl
results/<batch_id>/runs/<run_id>/todo_snapshots.jsonl
results/<batch_id>/runs/<run_id>/validation.json
```

## Tests

Add unit tests and fake server integration tests.

Required test areas:

- command builder
- worktree creation
- worktree path output
- health success/timeout
- cwd success/mismatch
- server info output
- restart on mismatch
- prompt gating
- SSE parser
- live state update
- JSONL flushing
- idle detection
- validation
- manifest cleanup

Run:

```bash
uv run pytest
```

## Completion report

Report:

- implemented modules
- implemented CLI commands/options
- output file examples
- test list
- test result
- known limitations
