# Data Model

## Stored result metadata

Each CLI `run` derives state from one eval-feia base directory under the home directory. The base defaults to `$HOME/.eval-feia`, or `EVAL_FEIA_BASE_DIR` when set. Durable records are written under `<base>/<run-id>/results`, unless `EVAL_FEIA_RESULTS_DIR` intentionally overrides only the results root:

```text
results/
  .eval-feia-results
  index.jsonl
  runs/<run-id>/
    metadata.json
    output.txt
    stdout.log
    stderr.log
    run.log
    summary.txt
```

`metadata.json` keeps stable keys for durable local history and for SQLite index backfill:

```json
{
  "run_id": "20260517-143012-a1b2c3",
  "created_at": "2026-05-17T14:30:12+09:00",
  "finished_at": "2026-05-17T14:31:00+09:00",
  "status": "success",
  "cwd": "/abs/path/repo",
  "output_dir": "/home/user/.eval-feia/20260517-143012-a1b2c3/results",
  "branch": "HEAD",
  "label": "smoke",
  "command": null,
  "exit_code": 0
}
```

The log files are local debugging artifacts and may contain command output or error text from the run environment.

## Manifest

`manifest.json` is the authoritative cleanup and provenance record. Generated output and worktree roots also carry eval-feia marker files that cleanup validates before deleting root directories.

```json
{
  "schema_version": 1,
  "run_id": "20260514-123456-a1b2c3",
  "label": "command body test",
  "created_at": "2026-05-14T12:34:56+09:00",
  "repo": {
    "path": "/abs/path/repo",
    "base_ref": "HEAD",
    "base_sha": "abc123"
  },
  "server": {
    "url": "http://127.0.0.1:4096",
    "version": "1.x.x"
  },
  "output_dir": "/home/user/.eval-feia/20260514-123456-a1b2c3/output",
  "worktree_root": "/home/user/.eval-feia/20260514-123456-a1b2c3/worktrees",
  "db_path": "/home/user/.eval-feia/eval-feia.sqlite3",
  "candidates": [
    {
      "id": "command-body-test",
      "eval_id": null,
      "requested_branch_name": null,
      "branch_name": "eval/20260514-123456-a1b2c3/command-body-test",
      "worktree_path": "/home/user/.eval-feia/20260514-123456-a1b2c3/worktrees/command-body-test",
      "result_dir": "/home/user/.eval-feia/20260514-123456-a1b2c3/output/candidates/command-body-test",
      "session_id": "ses_...",
      "status": "completed"
    }
  ]
}
```

`label` is a run-level display value only and must not be repeated as candidate metadata,
used directly as a path, or used as a Git ref. `branch_name` is the Git branch actually
created for the worktree after run scoping, sanitization, and collision suffixing. Worktree
directories are intentionally simple: the run ID is the grouping directory, and each candidate
gets a candidate-id leaf directory. Base ref and SHA metadata stay in manifest and result
records instead of being repeated in path names. `eval_id` is `null` when it would duplicate
the candidate ID.

## Candidate result

```json
{
  "candidate_id": "command-body-test",
  "eval_id": null,
  "base_ref": "HEAD",
  "base_sha": "abc12345...",
  "requested_branch_name": null,
  "branch_name": "eval/20260514-123456-a1b2c3/command-body-test",
  "status": "passed",
  "worktree_path": "/abs/path/.../20260514-123456-a1b2c3/command-body-test",
  "session_id": "ses_...",
  "started_at": "...",
  "completed_at": "...",
  "duration_seconds": 123.4,
  "opencode": {
    "session": "session.json",
    "messages": "messages.json",
    "children": "children.json",
    "todo": "todo.json",
    "diff": "diff.json",
    "file_status": "file-status.json"
  },
  "local": {
    "git_status": "git-status.txt",
    "git_diff": "local-git-diff.patch",
    "validation": "validation.json"
  },
  "summary": {
    "files_changed": 5,
    "additions": 120,
    "deletions": 13,
    "final_output_file": "final-output.md"
  },
  "error": null
}
```

## Error record

```json
{
  "kind": "timeout",
  "message": "candidate exceeded timeout_seconds=3600",
  "recoverable": true,
  "details": {}
}
```

Recommended error kinds:

```text
config_error
server_unavailable
health_failed
directory_context_mismatch
git_error
session_create_failed
prompt_failed
permission_required
timeout
abort_failed
collection_failed
validation_failed
cleanup_safety_failed
unexpected_error
```

## Validation record

```json
{
  "commands": [
    {
      "name": "unit-tests",
      "command": "pytest -q",
      "cwd": "/abs/path/worktree",
      "started_at": "...",
      "completed_at": "...",
      "exit_code": 0,
      "timeout": false,
      "stdout_file": "validation/unit-tests.stdout.log",
      "stderr_file": "validation/unit-tests.stderr.log",
      "required": true
    }
  ],
  "passed": true
}
```

## SQLite metadata index

Generated artifact files and durable stored-result files remain authoritative. The local SQLite database is a query index stored at
`<base>/eval-feia.sqlite3` by default, or at `EVAL_FEIA_DB_PATH` when that environment variable is set.

Default DB paths are recorded in new run manifests so `clean --delete-index` can delete them through the same manifest validation flow. Custom `EVAL_FEIA_DB_PATH` databases are not deleted by `clean --delete-index`; remove them manually when needed.

Schema versioning uses `PRAGMA user_version`. Version 1 contains:

- `runs`: one row per run with run ID, timestamps, status (`pending`, `running`,
  `success`, `failed`, `cancelled`), cwd/repo/branch/label, command/prompt metadata,
  output/result/summary paths, exit code, duration, error message, and `metadata_json`.
- `run_events`: append-only run lifecycle messages keyed by `run_id`.

The DB enables WAL, `busy_timeout`, and foreign keys on access. Large stdout/stderr or
collected opencode payloads are not stored in SQLite; only paths and metadata are indexed.
