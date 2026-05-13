# Worktree Specification

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Purpose

Each evaluation run must start from an isolated file-system snapshot.

Git worktrees provide isolated working directories while sharing object storage.

## Base commit resolution

The runner accepts `--branch`.

Resolve it to a commit SHA before creating run worktrees.

Prefer detached worktrees.

Do not check out the same branch in multiple concurrent worktrees.

## Directory layout

Recommended layout:

```text
/tmp/eval-feia/
  batch-<timestamp>-<id>/
    run-001/
      worktree/
      home/
      tmp/
      logs/
      artifacts/
    run-002/
      worktree/
      home/
      tmp/
      logs/
      artifacts/
```

## Creation

The worktree manager must:

1. create run directory
2. create detached worktree
3. resolve absolute path
4. print path immediately
5. write path to run metadata
6. emit progress event

Rich mode:

```text
run-001 | worktree | /tmp/eval-feia/batch/run-001/worktree
```

JSONL mode:

```json
{"type":"worktree_created","run_id":"run-001","path":"/tmp/eval-feia/batch/run-001/worktree"}
```

## Metadata

Store:

```json
{
  "worktree": {
    "path": "/tmp/eval-feia/batch/run-001/worktree",
    "base_ref": "main",
    "base_commit": "abc123",
    "created_at": "2026-05-13T00:00:00+09:00"
  }
}
```

## Cleanup

Cleanup must be manifest-based.

Never delete directories by broad glob alone.

## Tests

Required tests:

- worktree path is absolute
- path is printed after creation
- path is stored in manifest
- concurrent runs get distinct paths
- cleanup removes only manifest-listed paths


## Additional requirement: worktree path output

When a worktree is created, the CLI must immediately output the resolved worktree path.

Human output example:

```text
[run-001] worktree: /tmp/eval-feia/batch-20260513/run-001/worktree
```

JSONL output example:

```json
{"type":"worktree_created","run_id":"run-001","path":"/tmp/eval-feia/batch-20260513/run-001/worktree","commit":"abc123"}
```
