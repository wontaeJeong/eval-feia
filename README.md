# eval-feia

`eval-feia` is a local, REST-only CLI evaluator for running opencode coding experiments across isolated git worktrees.

The server lifecycle stays external: start `opencode serve` yourself, then run evaluations against that HTTP endpoint. The CLI has four top-level commands: `run`, `list`, `results`, and `clean`.

```bash
eval-feia run "Fix the issue described in README" --repo . --branch HEAD --attempts 1
eval-feia run --prompt-file examples/prompt.md --repo . --command bash
eval-feia run "..." --base-dir ./eval-state
eval-feia run "..." --no-progress
eval-feia run "..." --quiet

eval-feia list --limit 5
eval-feia list --base-dir ./eval-state
eval-feia list --output-dir ./custom-runs
eval-feia list --json
eval-feia list --status success --branch HEAD --limit 5

eval-feia results show <run-id>
eval-feia results path <run-id>
eval-feia results file <run-id> output.txt

eval-feia clean ~/.eval-feia/<run-id>/output/manifest.json
eval-feia clean --results --dry-run
```

All default eval-feia state is derived from one base directory under the home directory. The base defaults to `$HOME/.eval-feia`, or `EVAL_FEIA_BASE_DIR` when set. Each `run` writes generated run artifacts under `<base>/<run-id>/output`, generated worktrees under `<base>/<run-id>/worktrees`, and durable result records under `<base>/<run-id>/results`. Set `EVAL_FEIA_RESULTS_DIR` only when you intentionally want durable results outside that per-run base layout.

`clean` with a manifest removes only generated worktrees and generated run artifacts. Use `clean --results` only when you intentionally want to remove the stored results root.

A run can define one human-readable label used in run-level logs and summaries:

```bash
eval-feia run "..." --label "command body test"
```

Generated worktrees are grouped by run ID and candidate ID, while the created Git branch names include the run ID to avoid cross-run collisions. `result.json` / `run-summary.json` record the created branch, base ref, and base SHA.

Use `eval-feia list` to inspect generated run artifacts under `<base>/<run-id>/output` before choosing a manifest for `clean`:

```text
RUN                      CREATED                    MODIFIED                   STATUS   LABEL       BRANCH                         OUTPUT                         RESULT
20260514-123456-a1b2c3   2026-05-14T12:34:56+09:00 2026-05-14T12:40:00+09:00 success  command run eval/20260514-a1b2/cand-001 /home/user/.eval-feia/20260514-123456-a1b2c3/output /home/user/.eval-feia/20260514-123456-a1b2c3/output/run-summary.json
```

`eval-feia list` is the single run-listing command. It reads generated artifact directories and stored result metadata from local files, deduplicates by run ID, and supports `--status`, `--branch`, `--label`, `--limit`, `--base-dir`, `--output-dir`, and `--json` without a database.

Live progress logging is enabled by default. During each trial, `run` subscribes to `GET /event`, filters events by the opencode `sessionID`, and prints concise status/tool/todo/diff/permission lines with a trial prefix. Use `--no-progress` or `--quiet` to hide progress logs while keeping the final result output. The opencode server must already be running; `eval-feia` never starts or stops `opencode serve`.

Example progress output:

```text
[trial 1/2][id=cand-001][session=ses_...][branch=eval/run/cand-001][worktree=/abs/path] session status: busy
[trial 1/2][id=cand-001][session=ses_...][branch=eval/run/cand-001][worktree=/abs/path] tool started: bash
[trial 1/2][id=cand-001][session=ses_...][branch=eval/run/cand-001][worktree=/abs/path] session status: idle
```

## Install For Development

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

## MVP Guarantees

- Does not start, stop, restart, dispose, or kill `opencode serve`.
- Does not shell out to `opencode run --attach`.
- Uses `POST /session/{id}/message` for prompt execution by default.
- Uses `POST /session/{id}/command` when `--command` or `run.command` is set; the prompt text is sent as command `arguments`.
- Uses `GET /event` as an SSE stream for optional live progress display.
- Uses `POST /session/{id}/prompt_async` only if a future async mode explicitly needs it; session events are filtered from `/event` by `sessionID`.
- Sends worktree directory context on every worktree-specific opencode request.
- Uses `directory=<encoded-path>` for `GET`/`HEAD` and `x-opencode-directory` for non-GET requests.
- Creates worktrees, executes, collects, validates, summarizes, stores metadata in local files, and prints the final result from `run`.
- Lists generated run artifacts read-only with `list`.
- Lists generated artifacts and stored result history read-only with `list`, and inspects individual stored results with `results show`, `results path`, and `results file`.
- Deletes only manifest-recorded generated resources from `clean`; stored results are removed only with `clean --results`.

See `docs/` for the full product, REST, CLI, safety, and testing specs.
