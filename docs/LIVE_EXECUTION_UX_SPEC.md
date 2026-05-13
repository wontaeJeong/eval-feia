# Live Execution UX Specification

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Goal

The user must see agent execution progress while OpenCode is running.

## Modes

### Rich mode

Default human mode.

Table columns:

```text
Run | Port | Phase | Health | CWD | Msg | Tool | Child | Todo | Quiet | Elapsed | Note
```

Cells must be short.

### JSONL mode

Automation mode.

Each progress event is one JSON line. Flush every line.

Example:

```json
{"type":"run_progress","run_id":"run-001","phase":"running","msg":12,"tool":4,"child":1,"todo":"running","quiet":0,"elapsed_ms":32000}
```

### No-live mode

Use existing log style.

No Rich Live table.

## Required phase sequence

```text
queued
worktree
server-starting
server-health
cwd-check
server-info
server-ready
session-create
sse-connect
prompt-send
running
idle-wait
completed
failed
timeout
cleanup
```

Additional restart phases:

```text
server-mismatch
server-stopping
server-restarting
server-restart-exhausted
```

## SSE start order

SSE listener must connect before prompt submission.

The runner must receive a connection signal before sending the prompt.

## Live state fields

Track:

- run_id
- port
- phase
- health
- cwd
- message_count
- tool_call_count
- child_session_count
- todo_status
- quiet_seconds
- elapsed_seconds
- note
- restart_count
- worktree_path

## Event sources

Merge:

- SSE events
- `/session/status`
- `/session/:id/children`
- `/session/:id/todo`
- completion detector

## Renderer requirements

Renderer must not block prompt submission or SSE reading.

Prompt submission must not block renderer updates.

## Debug metadata

Store:

```json
{
  "live_summary": {
    "sse_endpoint": "/global/event",
    "sse_listener_started_at": null,
    "sse_connected_at": null,
    "prompt_sent_at": null,
    "first_event_at": null,
    "last_event_at": null,
    "total_sse_events": 0,
    "sse_parser_errors": 0,
    "total_status_polls": 0,
    "total_children_polls": 0,
    "total_todo_polls": 0,
    "renderer_refresh_count": 0,
    "final_phase": "completed"
  }
}
```
