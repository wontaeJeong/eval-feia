# Fake OpenCode Server Spec

Default tests must not call real OpenCode or LLM providers.

## Required fake endpoints

```text
GET  /global/health
GET  /path
GET  /project/current
POST /session
GET  /session/status
GET  /session/:id
GET  /session/:id/children
GET  /session/:id/todo
POST /session/:id/prompt_async
POST /session/:id/message
GET  /session/:id/message
GET  /session/:id/diff
GET  /event
GET  /global/event
```

## Required scenarios

### Healthy path

- health ok
- version match
- cwd match
- SSE emits events
- prompt is accepted

### Version mismatch then restart

- first attempt reports wrong version
- prompt is not sent to first server
- server is terminated
- second attempt reports correct version
- prompt is sent only to second server

### CWD mismatch then restart

- first attempt reports wrong cwd
- prompt is not sent
- server restarts
- final server reports expected cwd

### SSE trajectory

Fake SSE stream should emit at least:

```text
server.connected
message.updated
tool.call.started
tool.call.completed
```

## Test assertions

- worktree path event is emitted
- server_info event is emitted
- SSE listener starts before prompt
- prompt does not block live state updates
- JSONL output is valid and flushed
- run.json contains server_info and live_summary
