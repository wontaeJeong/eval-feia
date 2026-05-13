# OpenCode Integration

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Version-pinned launch

Use a command builder that produces:

```bash
bunx -p opencode-ai@<version> opencode serve --hostname 127.0.0.1 --port <port>
```

The command builder must be unit-tested.

## Environment isolation

Each run gets its own environment.

Set:

```bash
HOME=<run_home>
XDG_CONFIG_HOME=<run_home>/.config
XDG_CACHE_HOME=<run_home>/.cache
TMPDIR=<run_tmp>
OPENCODE_SERVER_USERNAME=opencode
OPENCODE_SERVER_PASSWORD=<random>
```

Do not dump the full environment into logs.

## Process group

Start the server in its own process group.

On restart or cleanup:

1. terminate group
2. wait grace period
3. kill group if still alive
4. mark termination result

## Readiness sequence

The runner must follow this order:

```text
server-starting
server-health
cwd-check
server-info
server-ready
session-create
sse-connect
prompt-send
running
```

## Version comparison

Compare requested version with reported version from `/global/health`.

Allowed values:

- `match`
- `mismatch`
- `unknown`

Mismatch triggers restart by default.

## CWD comparison

Expected cwd is resolved worktree path.

Actual cwd is extracted from `/path` or `/project/current`.

Compare using `Path.resolve()`.

Mismatch triggers restart by default.

## Restart logic

Restart triggers:

- `version_check == mismatch`
- `cwd_check == mismatch`

Restart limit:

- default `2`
- configurable by `--max-server-restarts`

Restart can be disabled by `--no-restart-on-mismatch`.

If disabled, mismatch fails the run before prompt submission.

## Server info output

After readiness success, emit:

```json
{
  "type": "server_info",
  "run_id": "run-001",
  "pid": 12345,
  "hostname": "127.0.0.1",
  "port": 4096,
  "base_url": "http://127.0.0.1:4096",
  "requested_version": "1.4.6",
  "reported_version": "1.4.6",
  "version_check": "match",
  "expected_cwd": "/tmp/eval-feia/batch/run-001/worktree",
  "actual_cwd": "/tmp/eval-feia/batch/run-001/worktree",
  "cwd_check": "ok",
  "restart_count": 0
}
```

## Prompt gating

Prompt submission requires:

- server process alive
- health ok
- server info emitted
- version not mismatched
- cwd not mismatched
- session exists
- SSE connected

If any condition fails, do not send the prompt.
