# Server Info and Restart Specification

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Goal

After `opencode serve` starts, show what was actually served.

If the actual server version or cwd does not match the requested state, kill and restart the server.

## Server info fields

Store and print:

- run_id
- pid
- hostname
- port
- base_url
- health_url
- requested_version
- reported_version
- version_check
- expected_cwd
- actual_cwd
- cwd_check
- restart_count
- server_start_elapsed_ms

## Rich summary

Use short table cells.

```text
Run | PID | Port | Phase | Version | CWD | Restarts | Elapsed | Note
```

## JSONL event

```json
{"type":"server_info","run_id":"run-001","pid":12345,"port":4096,"version_check":"match","cwd_check":"ok","restart_count":0}
```

## Mismatch policy

By default:

- version mismatch restarts server
- cwd mismatch restarts server
- mismatched attempt never receives prompt

## Restart events

```json
{"type":"server_mismatch","run_id":"run-001","reason":"version_mismatch","expected":"1.4.6","actual":"1.4.5"}
{"type":"server_restart","run_id":"run-001","action":"stopping","pid":12345,"restart_count":1}
{"type":"server_restart","run_id":"run-001","action":"starting","port":4096,"restart_count":1}
```

## Restart history

Store:

```json
{
  "server_restart_history": [
    {
      "attempt": 1,
      "pid": 12345,
      "reason": "version_mismatch",
      "requested_version": "1.4.6",
      "reported_version": "1.4.5",
      "expected_cwd": "/tmp/eval-feia/batch/run-001/worktree",
      "actual_cwd": "/tmp/eval-feia/batch/run-001/worktree",
      "terminated": true,
      "killed": false,
      "elapsed_ms": 3200
    }
  ]
}
```

## Tests

Required tests:

- server info emitted after readiness
- server info written to run.json
- version mismatch restarts before prompt
- cwd mismatch restarts before prompt
- prompt is blocked until server info ok
- restart kills old process group
- restart exhaustion fails run
