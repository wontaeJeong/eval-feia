# Data Schema

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Directory schema

```text
results/
  batch-<id>/
    manifest.json
    summary.json
    summary.csv
    runs/
      run-001/
        run.json
        prompt.txt
        opencode.log
        events.jsonl
        status_snapshots.jsonl
        children_snapshots.jsonl
        todo_snapshots.jsonl
        diff.patch
        validation.json
        artifacts/
```

## manifest.json

Required fields:

```json
{
  "batch_id": "batch-20260513-000001",
  "created_at": "2026-05-13T00:00:00+09:00",
  "repo": "/path/to/repo",
  "base_ref": "main",
  "base_commit": "abc123",
  "opencode_version": "1.4.6",
  "runs": []
}
```

## run.json

Required top-level fields:

```json
{
  "run_id": "run-001",
  "batch_id": "batch-20260513-000001",
  "status": "completed",
  "failure_class": "none",
  "worktree": {},
  "server_health": {},
  "cwd_check": {},
  "server_info": {},
  "server_restart_history": [],
  "live_summary": {},
  "metrics": {},
  "validation": {}
}
```

## summary.csv

Columns:

- batch_id
- run_id
- status
- failure_class
- model
- provider
- opencode_version
- worktree_path
- port
- server_restart_count
- total_messages
- total_tool_calls
- total_subagent_run
- total_operational_ms
- validation_passed
- task_success
- error_message

## Progress JSONL

Events are line-delimited JSON.

Required event types:

- `worktree_created`
- `server_info`
- `server_mismatch`
- `server_restart`
- `run_progress`
- `run_completed`
- `run_failed`
