# CLI Spec

## Command: `eval-feia run`

Runs the full evaluation pipeline.

### Usage

```bash
eval-feia run "Fix the failing tests" --repo . --branch HEAD --attempts 1
```

Use `--prompt-file` when the prompt is stored on disk:

```bash
eval-feia run --prompt-file ./prompt.md --repo . --branch HEAD --attempts 3 --command bash --output-dir ./.eval-feia/runs
```

For a one-off eval, inline prompt, branch, and a run-level label can be supplied directly:

```bash
eval-feia run "..." --label "foo test"
```

Provide only one prompt source: the positional prompt argument or `--prompt-file`.

`--command <name>` runs an opencode slash command. The prompt file content is sent to opencode as the command `arguments`. A leading slash is accepted in CLI input, so `--command /bash` sends `"bash"` in the HTTP request body.

### Required inputs

- opencode server URL
- git repository path
- base ref
- number of attempts/candidates
- prompt text or prompt file
- optional slash command name
- output directory

### Output

The command prints:

- server health/version
- run ID
- repository path, base ref/SHA, output directory, worktree root, execution mode, and
  validation command count
- progress lines for server preflight, output setup, worktree creation, candidate execution,
  and summary writing
- generated worktree table with per-candidate index and worktree path
- run label when provided
- per-candidate session IDs
- per-candidate status updates
- final plain summary table without repeating run metadata already printed before execution

The command writes:

- manifest
- per-candidate session metadata
- messages
- child sessions
- todo state
- opencode diff
- local git diff
- validation result
- result JSON and summary JSON with run-level `label`, `base_ref`, `base_sha`,
  `branch_name`, `worktree_path`, `session_id`, and status
- final summary markdown and JSON
- run metadata in the local SQLite index at `<output-root>/eval-feia.sqlite3`, unless
  `EVAL_FEIA_DB_PATH` overrides the database path

### Exit codes

Recommended exit codes:

- `0`: all candidates completed and all required validation passed
- `1`: one or more candidates failed or validation failed
- `2`: configuration error
- `3`: opencode server preflight failed
- `4`: git worktree setup failed
- `5`: cleanup safety check failed
- `130`: interrupted by user

## Command: `eval-feia clean`

Removes generated resources from a previous run.

### Usage

```bash
eval-feia clean .eval-feia/runs/<run-id>/manifest.json
```

### Behavior

- Reads manifest.
- Validates each path.
- Removes generated git worktrees using `git worktree remove` when possible.
- Removes candidate result directories if configured.
- Does not stop opencode server.
- Does not remove files outside manifest.

### Flags

```text
MANIFEST             Required. Manifest file to clean.
--dry-run            Print planned deletions without deleting.
--force              Continue after non-critical cleanup errors.
--db                 Also delete the SQLite metadata index database.
```

By default, clean preserves SQLite records and marks the run output as missing in
`metadata_json` after deleting manifest-recorded files. `clean --db` deletes only the
default database under the manifest output root; custom `EVAL_FEIA_DB_PATH` databases
must be removed manually.

## Command: `eval-feia list` / `eval-feia ls`

Lists recent run metadata from the local SQLite index. If the DB does not exist, it is
created lazily. If the DB is empty and file outputs already exist under `.eval-feia/runs`,
list performs a best-effort idempotent backfill from `manifest.json` and `run-summary.json`.

### Usage

```bash
eval-feia list --limit 10
eval-feia ls --status success --branch HEAD
EVAL_FEIA_DB_PATH=/tmp/eval-feia.sqlite3 eval-feia list --json
```

### Flags

```text
--limit N           Maximum number of runs to show.
--status STATUS     Filter by pending/running/success/failed/cancelled.
--branch BRANCH     Filter by branch/base ref.
--label LABEL       Filter by run label.
--json              Print a JSON array instead of the table.
```

Default table columns are short run ID, status, branch or label, cwd/repo name,
started/ended timestamps, duration, and output directory.

## Removed or deferred commands

These commands are intentionally out of MVP scope:

```text
serve      # server lifecycle is external
attach     # REST execution replaces CLI attach
collect    # run collects automatically
summary    # run summarizes automatically
report     # run writes report automatically
status     # not needed unless detached/background run mode is added later
```
