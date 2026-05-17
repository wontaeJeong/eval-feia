# PRD: eval-feia MVP

## Problem

We need a repeatable way to evaluate agentic code changes across multiple isolated git worktrees using a single existing opencode server. The previous design mixed three concerns: starting `opencode serve`, generating worktrees, and evaluating outputs. That made failures ambiguous: server startup, health checks, cwd/config mismatch, background sessions, and result collection were all entangled.

The MVP separates responsibilities.

## Product goal

Build a local CLI tool that:

1. Creates isolated git worktrees from a base repository/ref.
2. Runs the same evaluation prompt against each worktree through an existing `opencode serve` HTTP endpoint.
3. Ensures each opencode request is scoped to the correct worktree directory.
4. Collects messages, session metadata, child sessions, todo state, diffs, file status, validation logs, and final assistant output.
5. Writes a structured run directory.
6. Prints a final result summary automatically at the end of `run`.
7. Lists saved run results through a read-only `list` / `ls` command.
8. Cleans generated worktrees and result files only through a manifest-based `clean` command.

## Non-goals

The MVP does not:

- Start, restart, or kill `opencode serve`.
- Implement a TUI.
- Provide a web UI.
- Manage provider credentials.
- Depend on `opencode run --attach` subprocess behavior.
- Require additional user commands such as `collect`, `summary`, `report`, or `status`.

## User flow

1. User starts opencode separately.

```bash
opencode serve --hostname 127.0.0.1 --port 4096
```

2. User prepares a prompt string or prompt file.

3. User runs:

```bash
eval-feia run --prompt-file prompt.md --repo . --branch HEAD --attempts 1
```

4. `eval-feia` prints:

- opencode server health/version
- run ID, run label when provided, repository path, base ref/SHA, output directory, and worktree root
- progress lines for the major run phases
- effective worktree paths
- per-worktree session IDs
- per-worktree progress and validation status
- final plain summary table

5. User can inspect saved runs:

```bash
eval-feia list
eval-feia ls --limit 5
eval-feia list --output-dir ./custom-runs
```

6. User optionally removes generated resources:

```bash
eval-feia clean .eval-feia/runs/<run-id>/manifest.json
```

## MVP command surface

### `run`

`run` performs preflight, worktree creation, REST execution, collection, local validation, and final summary output.

### `list` / `ls`

`list` prints saved run results from the run output root, including custom roots passed with `--output-dir`. `ls` is an alias for the same handler. The command is read-only and tolerates missing or partial metadata.

### `clean`

`clean` removes generated worktrees and result artifacts recorded in a manifest. It never kills `opencode serve`; outside manifest mode, it may remove stored result history only through the explicit `clean --results` path after validating the eval-feia results root.

Stored result history is separate from manifest cleanup. It is removed only by the explicit
`clean --results` option after validating the eval-feia results root.

### `results`

`results list`, `results show <run-id>`, `results path <run-id>`, and `results cat <run-id> [file]` inspect stored local result history without contacting opencode.

## Acceptance criteria

A run is acceptable when all of the following are true:

- `GET /global/health` succeeds before any worktree execution.
- Each generated worktree path is printed immediately after creation.
- For every worktree, the opencode session is created with the correct effective directory context.
- The created session metadata is validated against the expected worktree directory when the server returns a directory field.
- The prompt is sent through REST, not through `opencode run --attach`.
- The tool waits until each execution is complete or times out.
- The tool collects messages, session info, children, todo state, diff, file status, and local git diff.
- The console output includes the result directory before execution and a final plain summary table after execution.
- `clean` only removes paths listed in the manifest unless `--results` is explicitly used for the stored results root.

## Success metrics

- Reproducible result directories.
- No accidental deletion outside `.eval-feia` and recorded git worktrees.
- No hidden dependency on subprocess attach semantics.
- Clear failure messages for server unavailability, wrong directory context, REST error, permission wait, timeout, and validation failure.
