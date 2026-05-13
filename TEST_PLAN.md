# Test Plan

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Test strategy

Unit tests cover deterministic logic.

Integration tests use a fake OpenCode server.

Real OpenCode/LLM tests are optional and must be marked separately.

## Unit tests

Required tests:

- command builder uses bunx and requested version
- port allocation avoids collisions
- worktree path is printed
- worktree path is recorded
- health check success
- health check timeout
- version mismatch detection
- cwd success from `/path`
- cwd success from `/project/current`
- cwd mismatch blocks prompt
- server info emitted
- restart on version mismatch
- restart on cwd mismatch
- restart exhaustion fails
- SSE parser basic event
- SSE parser multiline data
- SSE parser parse error count
- live state message updates
- live state tool updates
- JSONL flush
- Rich renderer refresh
- idle detection with child sessions
- validation JSON parse success
- secret scan failure

## Fake server integration tests

Fake server endpoints:

- `/global/health`
- `/path`
- `/project/current`
- `/session`
- `/global/event`
- `/event`
- `/session/status`
- `/session/:id/children`
- `/session/:id/todo`
- `/session/:id/prompt_async`
- `/session/:id/diff`

## Critical scenarios

### Happy path

1. create worktree
2. health ok
3. cwd ok
4. server info emitted
5. SSE connected
6. prompt sent
7. events streamed
8. idle detected
9. validation passed

### Version mismatch

1. first server reports wrong version
2. no prompt sent
3. process killed
4. server restarted
5. second server matches
6. prompt sent

### CWD mismatch

1. first server reports wrong cwd
2. no prompt sent
3. process killed
4. server restarted
5. cwd matches
6. prompt sent

### Live output bug prevention

1. SSE connects before prompt
2. prompt is async
3. renderer updates during run
4. JSONL flushes per line

## Commands

```bash
uv run pytest
uv run pytest --cov=eval_feia
```
