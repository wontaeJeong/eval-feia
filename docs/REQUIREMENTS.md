# Requirements

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Inputs

The app accepts:

- repository path
- run count
- concurrency
- base branch or commit
- prompt string or prompt file
- OpenCode skill
- provider ID
- model ID
- OpenCode version
- output directory
- temp root
- remote instrumentation URL
- timeout values
- live UX mode

## Required CLI commands

- `eval-feia run`
- `eval-feia collect`
- `eval-feia fetch`
- `eval-feia cleanup`
- `eval-feia inspect`

## Required options

- `--count`, `-n`
- `--concurrency`, `-j`
- `--prompt`, `-P`
- `--prompt-file`
- `--skill`, `-s`
- `--branch`, `-b`
- `--repo`
- `--worktree-root`
- `--output-dir`
- `--base-port`
- `--opencode-version`
- `--provider`
- `--model`
- `--server-start-timeout-seconds`
- `--health-poll-interval-seconds`
- `--cwd-check / --no-cwd-check`
- `--restart-on-mismatch / --no-restart-on-mismatch`
- `--max-server-restarts`
- `--idle-quiet-seconds`
- `--hard-timeout-seconds`
- `--no-live`
- `--json`

## Worktree path output

Immediately after creating a worktree, the CLI must emit a visible event.

Rich mode short row:

```text
run-001 | worktree | /tmp/eval-feia/batch/run-001/worktree
```

JSONL mode:

```json
{"type":"worktree_created","run_id":"run-001","path":"/tmp/eval-feia/batch/run-001/worktree"}
```

The same path must be stored in `run.json` and `manifest.json`.

## Runtime guards

Prompt submission is gated by:

1. server process alive
2. health ok
3. served info emitted
4. version not mismatched
5. cwd not mismatched
6. SSE listener connected
7. session created

## Completion

A run completes when the parent session and all descendant sessions are idle for the quiet period and no recent SSE events or todo updates are pending.

## Failure classes

- `none`
- `agent_failure`
- `validation_failure`
- `server_unhealthy`
- `server_version_mismatch`
- `cwd_mismatch`
- `server_restart_exhausted`
- `timeout`
- `harness_error`
