# Data Model

## Manifest

`manifest.json` is the authoritative cleanup and provenance record.

```json
{
  "schema_version": 1,
  "run_id": "20260514-123456-a1b2c3",
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
  "output_dir": "/abs/path/repo/.eval-feia/runs/20260514-123456-a1b2c3",
  "worktree_root": "/abs/path/repo/.eval-feia/worktrees/20260514-123456-a1b2c3",
  "candidates": [
    {
      "id": "command-body-test",
      "eval_id": "command-body-test",
      "label": "command body test",
      "requested_branch_name": "eval/command-body-test",
      "branch_name": "eval/command-body-test-2",
      "worktree_path": "/abs/path/repo/.eval-feia/worktrees/20260514-123456-a1b2c3/eval-command-body-test-2",
      "result_dir": "/abs/path/repo/.eval-feia/runs/20260514-123456-a1b2c3/candidates/command-body-test",
      "session_id": "ses_...",
      "status": "completed"
    }
  ]
}
```

`requested_branch_name` is the user-provided value, if any. `branch_name` is the Git branch
actually created for the worktree after sanitization and collision suffixing. `label` is a
display value only and must not be used directly as a path or Git ref.

## Candidate result

```json
{
  "candidate_id": "command-body-test",
  "eval_id": "command-body-test",
  "label": "command body test",
  "requested_branch_name": "eval/command-body-test",
  "branch_name": "eval/command-body-test-2",
  "status": "passed",
  "worktree_path": "/abs/path/.../eval-command-body-test-2",
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
