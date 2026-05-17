# CLI Spec

## Command: `eval-feia run`

Runs the full evaluation pipeline.

### Usage

```bash
eval-feia run --config eval-feia.yaml
```

Optional direct flags may override config values:

```bash
eval-feia run   --server-url http://127.0.0.1:4096   --repo .   --base-ref HEAD   --worktrees 3   --prompt-file ./prompt.md   --output-dir ./.eval-feia/runs
```

### Required inputs

- opencode server URL
- git repository path
- base ref
- number of worktrees or explicit candidate list
- prompt file
- output directory

### Output

The command prints:

- server health/version
- run ID
- generated worktree paths
- per-candidate session IDs
- per-candidate status updates
- final summary table
- final output directory path

The command writes:

- manifest
- per-candidate session metadata
- messages
- child sessions
- todo state
- opencode diff
- local git diff
- validation result
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

## Command: `eval-feia clean`

Removes generated resources from a previous run.

### Usage

```bash
eval-feia clean --manifest .eval-feia/runs/<run-id>/manifest.json
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
--manifest PATH      Required. Manifest file to clean.
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
