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
5. Writes structured run artifacts under the configured eval-feia base's per-run `output/` root.
6. Writes durable stored result history under the same base's per-run `results/` root unless `EVAL_FEIA_RESULTS_DIR` intentionally overrides it.
7. Prints live trial progress from opencode's event stream when enabled.
8. Prints a final result summary automatically at the end of `run`.
9. Lists generated run artifacts, stored result metadata, and individual stored result files through the read-only `result` command namespace.
10. Cleans generated worktrees and result files only through manifest-based `clean`; stored results use explicit `clean --results`.

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

- stored result output directory
- opencode server health/version
- run ID, run label when provided, repository path, base ref/SHA, generated artifact output directory, and worktree root
- progress lines for the major run phases
- effective worktree paths
- per-worktree session IDs
- per-worktree progress and validation status
- final plain summary table

5. User can inspect saved runs:

```bash
eval-feia result list
eval-feia result list --limit 5
eval-feia result list --base-dir ./eval-state
eval-feia result list --json
eval-feia result list --status success --branch HEAD
eval-feia result show <run-id>
eval-feia result path <run-id>
eval-feia result file <run-id> output.txt
```

6. User optionally removes generated resources:

```bash
eval-feia clean ~/.eval-feia/<run-id>/output/manifest.json
eval-feia clean --results
```

## MVP command surface

### `run`

`run` performs preflight, worktree creation, REST execution, event-stream progress logging, collection, local validation, final summary output, and stored result persistence.

### `result`

`result list` prints generated run artifacts from `<base>/<run-id>/output` and stored result metadata from `<base>/<run-id>/results`, including custom bases passed with `--base-dir`. The command is read-only and tolerates missing or partial metadata. `--status`, `--branch`, and `--label` filter local file metadata. `result show`, `result path`, and `result file` inspect stored local result history without contacting opencode.

### `clean`

`clean <manifest>` removes generated worktrees and result artifacts recorded in a manifest. It never kills `opencode serve` and never removes durable stored result history.

`clean --results` removes the validated durable stored-results root.

## Acceptance criteria

A run is acceptable when all of the following are true:

- `GET /global/health` succeeds before any worktree execution.
- Each generated worktree path is printed immediately after creation.
- For every worktree, the opencode session is created with the correct effective directory context.
- The created session metadata is validated against the expected worktree directory when the server returns a directory field.
- The prompt is sent through REST, not through `opencode run --attach`.
- The tool waits until each execution is complete or times out.
- The tool collects messages, session info, children, todo state, diff, file status, and local git diff.
- The console output includes the stored result directory before execution and a final plain summary table after execution.
- Generated artifacts are written under the configured eval-feia base's per-run `output/` root.
- Durable stored results are written under the same base's per-run `results/` root unless explicitly overridden.
- Live progress uses `GET /event` and filters events by session ID when progress logging is enabled.
- `result` works for generated run artifacts, stored result metadata, file-backed filters, and stored result inspection without contacting opencode.
- `clean` only removes paths listed in the manifest after generated-root marker validation; `clean --results` is required for stored results.

## Success metrics

- Reproducible generated artifact directories.
- Durable local stored result history.
- Queryable local run metadata from file-backed artifacts.
- No accidental deletion outside marker-validated `.eval-feia` generated roots, recorded git worktrees, or validated stored result roots.
- No hidden dependency on subprocess attach semantics.
- Clear failure messages for server unavailability, wrong directory context, REST error, permission wait, timeout, validation failure, and stored result inspection failure.
