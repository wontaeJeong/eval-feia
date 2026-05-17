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
5. Writes structured run artifacts under the configured output root.
6. Writes durable stored result history under `EVAL_FEIA_RESULTS_DIR` or `$HOME/.eval-feia/results`.
7. Indexes run metadata in a local SQLite database for filtered listing.
8. Prints a final result summary automatically at the end of `run-eval`.
9. Lists generated run artifacts through the read-only `list-run-artifacts` command.
10. Inspects durable stored results through read-only stored-result inspection commands.
11. Cleans generated worktrees and result files only through manifest-based `clean-run-artifacts`; stored results use `clean-stored-results`, and default SQLite DB deletion requires `clean-run-artifacts --delete-index`.

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
eval-feia run-eval --prompt-file prompt.md --repo . --branch HEAD --attempts 1
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
eval-feia list-run-artifacts
eval-feia list-run-artifacts --limit 5
eval-feia list-run-artifacts --output-dir ./custom-runs
EVAL_FEIA_DB_PATH=/tmp/eval-feia.sqlite3 eval-feia list-run-artifacts --json
eval-feia list-run-artifacts --status success --branch HEAD
```

6. User can inspect durable stored results:

```bash
eval-feia list-stored-results
eval-feia show-stored-result <run-id>
eval-feia print-stored-result-path <run-id>
eval-feia print-stored-result-file <run-id> output.txt
```

7. User optionally removes generated resources:

```bash
eval-feia clean-run-artifacts .eval-feia/runs/<run-id>/manifest.json
eval-feia clean-run-artifacts .eval-feia/runs/<run-id>/manifest.json --delete-index
eval-feia clean-stored-results
```

## MVP command surface

### `run-eval`

`run-eval` performs preflight, worktree creation, REST execution, collection, local validation, final summary output, stored result persistence, and SQLite metadata indexing.

### `list-run-artifacts`

`list-run-artifacts` prints generated run artifacts from the run output root by default, including custom roots passed with `--output-dir`. The command is read-only and tolerates missing or partial metadata.

When `EVAL_FEIA_DB_PATH` is set or `--status`, `--branch`, or `--label` is provided, `list-run-artifacts` reads the local SQLite metadata index instead and can backfill it from existing file outputs.

### `clean-run-artifacts`

`clean-run-artifacts` removes generated worktrees and result artifacts recorded in a manifest. It never kills `opencode serve` and never removes durable stored result history.

`clean-run-artifacts --delete-index` deletes only the manifest-recorded default SQLite database under the generated output root. Custom `EVAL_FEIA_DB_PATH` databases are never deleted automatically.

### Stored-result inspection commands

`list-stored-results`, `show-stored-result <run-id>`, `print-stored-result-path <run-id>`, and `print-stored-result-file <run-id> [file]` inspect stored local result history without contacting opencode.

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
- Generated artifacts are written under the configured output root.
- Durable stored results are written under the configured results root.
- SQLite run metadata is recorded when the index can be opened; index failures are surfaced as warnings during `run-eval` and exit code `6` during indexed `list-run-artifacts`.
- `list-run-artifacts` works for generated run artifacts and SQLite filters.
- stored-result inspection commands work without contacting opencode.
- `clean-run-artifacts` only removes paths listed in the manifest after generated-root marker validation; `clean-stored-results` is required for stored results, and `clean-run-artifacts --delete-index` is required for the manifest-recorded default SQLite DB.

## Success metrics

- Reproducible generated artifact directories.
- Durable local stored result history.
- Queryable local run metadata index.
- No accidental deletion outside marker-validated `.eval-feia` generated roots, recorded git worktrees, validated stored result roots, or manifest-recorded default DB files.
- No hidden dependency on subprocess attach semantics.
- Clear failure messages for server unavailability, wrong directory context, REST error, permission wait, timeout, validation failure, and storage inspection failure.
