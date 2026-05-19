# CLI Spec

## Command: `eval-feia run`

Runs the full evaluation pipeline.

```bash
eval-feia run "Fix the failing tests" --repo . --branch HEAD --attempts 1
eval-feia run --prompt-file ./prompt.md --repo . --branch HEAD --attempts 3 --command bash --base-dir ./.eval-feia
eval-feia run "..." --jobs 2
eval-feia run "..." --label "foo test" --no-progress
```

Provide only one prompt source: the positional prompt argument or `--prompt-file`.

At startup `run` prints the stored result location:

```text
Run ID: 20260517-143012-a1b2c3
Output directory: /home/user/.eval-feia/20260517-143012-a1b2c3/results
```

Runs, worktrees, and stored results share one base directory under the home directory. The base defaults to `$HOME/.eval-feia`, can be set with `EVAL_FEIA_BASE_DIR`, and can be overridden for a run with `--base-dir`. A run stores generated artifacts in `<base>/<run-id>/output`, worktrees in `<base>/<run-id>/worktrees`, and stored results in `<base>/<run-id>/results`. Set `EVAL_FEIA_RESULTS_DIR` only when stored results must live outside that per-run base layout.

`--command <name>` runs an opencode slash command. The prompt file content is sent to opencode as the command `arguments`. A leading slash is accepted in CLI input, so `--command /bash` sends `"bash"` in the HTTP request body.

Live progress logging is enabled by default. `--no-progress` disables progress logs, including per-trial event logs.

The opencode server must already be running. `eval-feia` does not start, stop, restart, dispose, or kill `opencode serve`.

### Output

The command prints:

- server health/version
- run ID
- repository path, base ref/SHA, output directory, worktree root, execution mode, and validation command count
- progress lines for server preflight, output setup, worktree creation, candidate execution, opencode event stream updates, and summary writing
- one metadata line when each trial starts, including candidate ID, branch, and worktree path
- run label when provided
- per-candidate session IDs and status updates
- final plain summary table without repeating run metadata already printed before execution

The command writes:

- stored result metadata, output, summary, and logs under `<base>/<run-id>/results`
- append-only `<base>/<run-id>/results/index.jsonl`
- manifest
- per-candidate session metadata
- messages
- child sessions
- todo state
- opencode diff
- local git diff
- validation result
- result JSON and summary JSON with run-level `label`, `base_ref`, `base_sha`, `branch_name`, `worktree_path`, `session_id`, status, elapsed time, and available token metrics
- final summary markdown and JSON

### Exit Codes

- `0`: all candidates completed and all required validation passed
- `1`: one or more candidates failed or validation failed
- `2`: configuration error
- `3`: opencode server preflight failed
- `4`: git worktree setup failed
- `5`: cleanup safety check failed
- `130`: interrupted by user

## Command: `eval-feia result`

Lists generated run artifacts and stored result metadata from local files, and inspects one stored result.

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

Behavior:

- Reads generated run directories under `<base>/<run-id>/output`.
- Reads stored result metadata under `<base>/<run-id>/results`.
- Prefers `manifest.json` and `run-summary.json` metadata when present.
- Falls back to run directory names, file paths, and modification time for partial results.
- Sorts newest modified runs first.
- Treats a missing output root as an empty list.
- Applies `--status`, `--branch`, and `--label` by filtering file-backed metadata.
- Shows one stored result with `result show <run-id>`.
- Prints one stored result directory with `result path <run-id>`.
- Prints one stored result file with `result file <run-id> <file>`.

Output includes run ID, created time, modified time, status, label when available, branch information when available, output directory, and result/metadata file path.

```text
RUN                      CREATED                    MODIFIED                   STATUS   LABEL       BRANCH                         OUTPUT                         RESULT
20260514-123456-a1b2c3   2026-05-14T12:34:56+09:00 2026-05-14T12:40:00+09:00 success  command run eval/20260514-a1b2/cand-001 /home/user/.eval-feia/20260514-123456-a1b2c3/output /home/user/.eval-feia/20260514-123456-a1b2c3/output/run-summary.json
```

Flags:

```text
--limit N           Show only the most recent N saved runs.
--base-dir PATH     Eval-feia base directory whose runs are inspected.
--status STATUS     Filter runs by pending/running/success/failed/cancelled/unknown.
--branch BRANCH     Filter runs by branch/base ref.
--label LABEL       Filter runs by label.
--json              Print JSON.
```

When there are no saved runs, the command prints:

```text
No saved runs found.
```

## Command: `eval-feia clean`

Removes generated run artifacts by manifest, or stored results with `--results`.

```bash
eval-feia clean ~/.eval-feia/<run-id>/output/manifest.json
eval-feia clean --results
eval-feia clean --results --dry-run
```

Rules:

- Manifest cleanup deletes only manifest-recorded generated worktrees, generated result directories, generated run output roots, and generated worktree roots.
- Every generated root must carry the eval-feia generated-root marker.
- `--results` removes the configured durable stored-results root instead of generated artifacts. It cannot be combined with a manifest or `--force`.
- `--dry-run` prints planned deletions without deleting.
- `--force` allows cleanup to continue after non-critical removal errors for manifest cleanup only.

Flags:

```text
MANIFEST            Manifest path for generated artifact cleanup.
--dry-run           Print planned deletions without deleting.
--force             Continue manifest cleanup after non-critical removal errors.
--results           Clean stored result history instead of generated artifacts.
--base-dir PATH     Eval-feia base directory used with --results.
```

## Intentionally Absent Commands

These remain out of scope:

```text
serve      # opencode server lifecycle is external
attach     # no opencode run --attach
collect    # run collects automatically
summary    # run summarizes automatically
report
status
list       # result list handles saved-run listing
results    # result handles stored result inspection
```
