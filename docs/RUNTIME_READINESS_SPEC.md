# Runtime Readiness Specification

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Goal

Prevent invalid runs caused by unhealthy OpenCode servers or mismatched runtime state.

## Health check

After starting `opencode serve`, poll:

```http
GET /global/health
```

Success requires:

- HTTP 200
- `healthy == true`
- version field exists or is explicitly recorded as unknown

## Health timeout

Configurable with:

- `--server-start-timeout-seconds`
- `--health-poll-interval-seconds`

If timeout occurs:

- do not create session
- do not send prompt
- set failure class `server_unhealthy`
- write metadata

## CWD check

After health success, verify cwd.

Use:

1. `/path`
2. `/project/current` fallback

Success requires resolved actual path equals resolved expected worktree path.

## Served info check

After health and cwd check, emit server info.

This is a gating condition before prompt submission.

## Restart on mismatch

Mismatch triggers:

- server stop
- process group terminate
- process group kill if needed
- restart attempt
- health check again
- cwd check again
- server info again

## Restart exhaustion

If restart limit is exceeded:

- do not send prompt
- set failure class `server_restart_exhausted`
- write restart history

## Metadata

Required fields:

```json
{
  "server_health": {},
  "cwd_check": {},
  "server_info": {},
  "server_restart_history": []
}
```
