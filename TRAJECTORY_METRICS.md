# Trajectory Metrics

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Goal

Quantify how the agent works, not just whether it succeeds.

## Core metrics

- `total_messages`
- `user_message_count`
- `assistant_message_count`
- `total_tool_calls`
- `tool_call_success_count`
- `tool_call_failure_count`
- `total_subagent_run`
- `max_session_depth`
- `total_todo_items`
- `todo_completed_count`
- `todo_failed_count`
- `total_operational_ms`
- `server_start_elapsed_ms`
- `idle_quiet_ms`
- `validation_retries`
- `validation_failures`
- `server_restart_count`
- `task_success`

## Operational vs task success

Separate runtime completion from task quality.

Runtime fields:

- `server_ready`
- `prompt_sent`
- `opencode_completed`
- `timeout`
- `harness_error`

Task fields:

- `artifact_found`
- `json_parse_ok`
- `autogen_load_ok`
- `validation_passed`
- `task_success`

## Source of truth

Local logs are source of truth.

Remote instrumentation metrics are enrichment.

## Event categories

Classify events into:

- message
- tool
- session
- subagent
- todo
- status
- file
- server
- restart
- validation
- error

## Run-level summary

Each run writes:

```json
{
  "metrics": {
    "total_messages": 0,
    "total_tool_calls": 0,
    "total_subagent_run": 0,
    "total_operational_ms": 0,
    "validation_retries": 0,
    "validation_failures": 0,
    "task_success": false
  }
}
```
