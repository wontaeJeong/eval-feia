# Task Breakdown

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Epic 1. Bootstrap

- create package layout
- add Typer CLI
- add pytest
- add rich, requests/httpx
- add pyproject scripts

## Epic 2. Worktree

- resolve base commit
- create detached worktree
- print path
- save manifest
- cleanup by manifest

## Epic 3. OpenCode runtime

- command builder
- process group launcher
- health check
- cwd check
- server info output
- restart on mismatch

## Epic 4. Prompt execution

- create session
- connect SSE
- send prompt async
- poll status/children/todo
- detect idle

## Epic 5. Live UX

- Rich Live table
- JSONL renderer
- no-live mode
- flush behavior

## Epic 6. Metrics

- parse events
- count messages/tools/subagents
- compute durations
- write summary

## Epic 7. Validation

- find artifact
- parse JSON
- secret scan
- task-specific checks

## Epic 8. Tests

- unit tests
- fake server tests
- CLI tests
- cleanup tests
