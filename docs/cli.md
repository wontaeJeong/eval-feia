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

### Exit codes

Recommended exit codes:

- `0`: all candidates completed and all required validation passed
- `1`: one or more candidates failed or validation failed
- `2`: configuration error
- `3`: opencode server preflight failed
- `4`: git worktree setup failed
- `5`: cleanup safety check failed
- `130`: interrupted by user

## Command: `eval-feia list` / `eval-feia ls`

Lists saved run results from the configured run output root. `ls` is an alias for `list` and uses the same handler.

### Usage

```bash
eval-feia list
eval-feia ls --limit 5
eval-feia list --output-dir ./custom-runs
eval-feia list --json
```

### Behavior

- Reads saved run directories under the same output root used by `run`; defaults to `.eval-feia/runs` and accepts `--output-dir` for custom roots.
- Prefers `manifest.json` and `run-summary.json` metadata when present.
- Falls back to the run directory name, file paths, and modification time for partial or legacy results.
- Sorts newest modified runs first.
- Treats a missing output root as an empty list.
- Does not delete or modify files.

### Output

Human output includes the run ID, created time, modified time, label when available,
branch information when available, output directory, and result/metadata file path.

```text
RUN                      CREATED                    MODIFIED                   LABEL       BRANCH                         OUTPUT                         RESULT
20260514-123456-a1b2c3   2026-05-14T12:34:56+09:00 2026-05-14T12:40:00+09:00 command run eval/20260514-a1b2/cand-001 /repo/.eval-feia/runs/...     /repo/.eval-feia/runs/.../run-summary.json
```

When there are no saved runs, the command prints:

```text
No saved runs found.
```

### Flags

```text
--limit N           Show only the most recent N saved runs.
--output-dir PATH   Run output root to inspect.
--json              Print saved runs as a JSON array.
```

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
```

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
