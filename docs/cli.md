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

At startup `run` prints the stored result location:

```text
Run ID: 20260517-143012-a1b2c3
Output directory: /home/user/.eval-feia/results/runs/20260517-143012-a1b2c3
```

Stored results default to `$HOME/.eval-feia/results`. Set `EVAL_FEIA_RESULTS_DIR` to override that root. The SQLite metadata index defaults to `<output-root>/eval-feia.sqlite3`; set `EVAL_FEIA_DB_PATH` to override that database path.

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
- repository path, base ref/SHA, output directory, worktree root, execution mode, and validation command count
- progress lines for server preflight, output setup, worktree creation, candidate execution, and summary writing
- generated worktree table with per-candidate index and worktree path
- run label when provided
- per-candidate session IDs
- per-candidate status updates
- final plain summary table without repeating run metadata already printed before execution

The command writes:

- stored result metadata, output, summary, and logs under `$HOME/.eval-feia/results/runs/<run-id>`
- append-only `$HOME/.eval-feia/results/index.jsonl`
- run metadata in the local SQLite index at `<output-root>/eval-feia.sqlite3`, unless `EVAL_FEIA_DB_PATH` overrides the database path
- manifest
- per-candidate session metadata
- messages
- child sessions
- todo state
- opencode diff
- local git diff
- validation result
- result JSON and summary JSON with run-level `label`, `base_ref`, `base_sha`, `branch_name`, `worktree_path`, `session_id`, and status
- final summary markdown and JSON

### Exit codes

Recommended exit codes:

- `0`: all candidates completed and all required validation passed
- `1`: one or more candidates failed or validation failed
- `2`: configuration error
- `3`: opencode server preflight failed
- `4`: git worktree setup failed
- `5`: cleanup safety check failed
- `6`: SQLite metadata index inspection failed
- `130`: interrupted by user

## Command: `eval-feia list`

Lists generated run artifacts from the configured run output root.

### Usage

```bash
eval-feia list
eval-feia list --limit 5
eval-feia list --output-dir ./custom-runs
eval-feia list --json
EVAL_FEIA_DB_PATH=/tmp/eval-feia.sqlite3 eval-feia list --json
eval-feia list --status success --branch HEAD
```

### Behavior

- By default, reads saved run directories under the same output root used by `run`; defaults to `.eval-feia/runs` and accepts `--output-dir` for custom roots.
- Prefers `manifest.json` and `run-summary.json` metadata when present.
- Falls back to the run directory name, file paths, and modification time for partial or legacy results.
- Sorts newest modified runs first.
- Treats a missing output root as an empty list.
- Does not delete or modify files.
- When `EVAL_FEIA_DB_PATH` or any SQLite filter is provided, reads recent run metadata from the local SQLite index instead. If the DB is empty and file outputs already exist, it performs a best-effort idempotent backfill from `manifest.json` and `run-summary.json`.

### Output

File-output listing includes the run ID, created time, modified time, label when available, branch information when available, output directory, and result/metadata file path.

```text
RUN                      CREATED                    MODIFIED                   LABEL       BRANCH                         OUTPUT                         RESULT
20260514-123456-a1b2c3   2026-05-14T12:34:56+09:00 2026-05-14T12:40:00+09:00 command run eval/20260514-a1b2/cand-001 /repo/.eval-feia/runs/...     /repo/.eval-feia/runs/.../run-summary.json
```

SQLite index listing uses short run ID, status, branch or label, cwd/repo name, started/ended timestamps, duration, and output directory.

When there are no saved runs, the command prints:

```text
No saved runs found.
```

### Flags

```text
--limit N           Show only the most recent N saved runs.
--output-dir PATH   Run output root to inspect.
--status STATUS     Filter indexed runs by pending/running/success/failed/cancelled.
--branch BRANCH     Filter indexed runs by branch/base ref.
--label LABEL       Filter indexed runs by run label.
--json              Print saved runs as a JSON array.
```

## Command: `eval-feia clean`

Removes generated resources from a previous run.

### Usage

```bash
eval-feia clean .eval-feia/runs/<run-id>/manifest.json
eval-feia clean .eval-feia/runs/<run-id>/manifest.json --delete-index
eval-feia clean --results --dry-run
```

### Behavior

- Reads manifest.
- Validates each path and eval-feia generated-root marker.
- Removes generated git worktrees using `git worktree remove` when possible.
- Removes candidate result directories if configured.
- Does not stop opencode server.
- Does not remove files outside manifest-recorded generated resources.
- Does not remove stored results.
- By default, preserves SQLite records and marks the run output as missing in `metadata_json` after deleting manifest-recorded files.
- `--delete-index` deletes only the default database under the manifest output root; custom `EVAL_FEIA_DB_PATH` databases must be removed manually.
- `--results` removes the configured durable stored-results root instead of generated artifacts. It cannot be combined with a manifest, `--force`, or `--delete-index`.

### Flags

```text
MANIFEST             Manifest file to clean.
--results            Remove the configured durable stored-results root.
--dry-run            Print planned deletions without deleting.
--force              Continue after non-critical cleanup errors.
--delete-index       Also delete the manifest-recorded default SQLite metadata index database.
```

`clean --results` validates that the target is an eval-feia-owned results root and rejects unexpected top-level entries before deleting anything.

## Command group: `eval-feia results`

Inspect locally stored run results without contacting opencode.

```bash
eval-feia results list
eval-feia results show <run-id>
eval-feia results path <run-id>
eval-feia results file <run-id> [file]
```

- `results list` prints `run_id`, `created_at`, `status`, `branch`, `label`, `cwd`, and `output_dir` newest first. If `index.jsonl` is missing or damaged, it scans `runs/*/metadata.json`.
- `results show <run-id>` prints metadata plus `summary.txt`, falling back to the start of `output.txt`.
- `results path <run-id>` prints only the absolute stored run directory for scripts.
- `results file <run-id> [file]` prints a file inside the run directory; the default is `output.txt`. Absolute paths and `..` traversal are rejected.

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

The former verbose command names (`run-eval`, `list-run-artifacts`, `clean-run-artifacts`, `clean-stored-results`, and standalone stored-result inspection commands) are intentionally not registered; use `run`, `list`, `results`, and `clean` instead.
