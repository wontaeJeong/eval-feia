# Product Requirements Document

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Objective

Build `eval-feia`, a Python CLI evaluation harness that runs OpenCode agents in isolated worktrees, sends a standardized prompt, captures the agent trajectory in real time, validates the produced output, and writes JSON/CSV reports.

## Primary users

The primary users are developers and AI platform engineers who compare LLM coding-agent behavior under controlled conditions.

## Main success criteria

The product is successful when a user can run one command and get reproducible evaluation results for multiple agent runs.

A successful batch must:

- create one isolated Git worktree per run
- print the worktree path immediately after creation
- start one version-pinned OpenCode server per run
- check server health before sending any prompt
- verify that served cwd matches the requested worktree
- print actual served server information
- restart the server if version or cwd mismatches
- connect to SSE before prompt submission
- show live trajectory state in the CLI
- detect idle completion across parent and child sessions
- collect local event logs as source of truth
- optionally fetch remote instrumentation metrics
- validate the produced AutoGen config
- save complete run artifacts
- provide unit and integration tests

## Default task

The default prompt is:

> 웹 검색 후 Knox 메일 리포트 에이전트 작성

The default skill is:

> impl

## Functional requirements

### F1. Batch execution

The CLI must support running multiple evaluations in one batch.

Default count is 20. Concurrency defaults to 1.

### F2. Worktree isolation

Each run must create its own worktree under a temp root.

The harness must print the worktree path as soon as it is created.

The path must appear in:

- CLI output
- JSONL progress output
- `run.json`
- `manifest.json`

### F3. OpenCode version pinning

The harness must not call a globally installed `opencode` binary directly.

It must build a command equivalent to:

```bash
bunx -p opencode-ai@<version> opencode serve --hostname 127.0.0.1 --port <port>
```

The requested version and reported version must be recorded.

### F4. Server readiness

After `opencode serve` starts, the harness must poll `/global/health`.

Prompt submission is forbidden until health is confirmed.

### F5. CWD verification

After health is confirmed, the harness must call `/path` and, if needed, `/project/current`.

The served cwd or project root must match the resolved worktree path.

### F6. Served info output

After health and cwd checks, the CLI must print actual served information.

This includes PID, port, base URL, requested version, reported version, version check result, expected cwd, actual cwd, and restart count.

### F7. Restart on mismatch

If served cwd or OpenCode version mismatches, the harness must stop the process group and restart the server.

The server may be restarted up to `--max-server-restarts`.

Prompt submission is forbidden for mismatched server attempts.

### F8. Live execution UX

The harness must connect to SSE before sending the prompt.

The CLI must show live updates for message count, tool call count, child session count, todo status, quiet period, elapsed time, and current phase.

### F9. Trajectory logging

All SSE events, status snapshots, child session snapshots, todo snapshots, prompt requests, health checks, cwd checks, restarts, and validation results must be written to files.

### F10. Validation

After completion, validate that the expected output exists, is valid JSON, can be interpreted as AutoGen Teams Component Config, and does not contain hardcoded secrets.

### F11. Reports

The harness must write:

- `manifest.json`
- `summary.json`
- `summary.csv`
- `runs/<run_id>/run.json`
- `runs/<run_id>/events.jsonl`
- `runs/<run_id>/status_snapshots.jsonl`
- `runs/<run_id>/children_snapshots.jsonl`
- `runs/<run_id>/todo_snapshots.jsonl`
- `runs/<run_id>/diff.patch`
- `runs/<run_id>/validation.json`

## Non-functional requirements

### Reproducibility

Record all parameters that can affect results.

### Security

Bind server to `127.0.0.1`. Use `OPENCODE_SERVER_PASSWORD`. Never log secrets.

### Testability

Most tests must use fake OpenCode servers and mocks. Real LLM or network calls must not be required for unit tests.

### Reliability

One run failure must not abort the whole batch.

### UX

CLI output must be useful during long runs. Tables must contain short fields only. Long details go to logs and JSON files.
