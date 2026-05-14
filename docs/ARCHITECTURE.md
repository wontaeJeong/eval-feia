# Architecture

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Components

### CLI layer

Typer-based command entrypoint.

Responsibilities:

- parse options
- display live progress
- emit JSONL progress in automation mode
- invoke orchestrator commands

### Batch orchestrator

Creates a batch ID and schedules run workers according to concurrency.

Responsibilities:

- allocate run IDs
- create result directories
- coordinate parallel execution
- merge summaries

### Run worker

Owns one evaluation run.

Responsibilities:

- create worktree
- start OpenCode server
- perform health and cwd checks
- restart on mismatch
- create session
- connect SSE
- submit prompt
- monitor execution
- validate output
- write artifacts

Session/worktree model:

- One isolated worktree is created per EvalJob/AgentRun.
- One root OpenCode session is created per EvalJob/AgentRun.
- Child sessions under that root are treated as subagent/background Task work.
- Worktree isolation and OpenCode server lifecycle are separate concerns.
- MVP can run serve-per-worktree, and can later extend to warm server pools while keeping root_session_id tracking.

### OpenCode client

Thin HTTP client for OpenCode server.

Responsibilities:

- authentication
- health check
- cwd/project lookup
- session creation
- prompt async submission
- status polling
- child/todo polling
- diff/message fetching
- SSE stream reading

### Process manager

Starts and stops OpenCode server processes.

Responsibilities:

- build version-pinned command
- set isolated environment variables
- launch process group
- graceful terminate
- force kill
- confirm process exit

### Worktree manager

Creates and removes per-run Git worktrees.

Responsibilities:

- resolve base commit
- create detached worktree
- print path
- record path
- cleanup via manifest

### Live state store

Maintains current state for each run.

Responsibilities:

- phase tracking
- counters
- health/cwd/server info
- restart count
- elapsed time
- quiet seconds
- notes

### Renderers

Two renderers are required.

Rich renderer:

- terminal table
- human-friendly
- short cells only

JSONL renderer:

- line-delimited JSON
- flushed on every event
- CI-friendly

### Validator

Checks final artifacts.

Responsibilities:

- JSON parse
- schema checks
- AutoGen config structure
- secret detection
- task-specific requirements

## Execution flow

1. create batch
2. create run directories
3. create worktree
4. print worktree path
5. start OpenCode server
6. poll health
7. verify cwd
8. emit server info
9. restart if mismatch
10. create session
11. connect SSE
12. send prompt async
13. monitor SSE and polling
14. detect idle completion
15. collect messages/diff/artifacts
16. validate result
17. write summaries
18. cleanup if requested

## Data ownership

Local raw logs are source of truth.

Remote instrumentation data is enrichment only.
