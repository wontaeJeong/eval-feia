# eval-feia

`eval-feia` is a local, REST-only CLI evaluator for running opencode coding experiments across isolated git worktrees.

The server lifecycle stays external: start `opencode serve` yourself, then run evaluations against that HTTP endpoint. The MVP exposes `run`, read-only `list` / `ls`, `clean`, and local `results` inspection commands.

```bash
eval-feia run "Fix the issue described in README" --repo . --branch HEAD --attempts 1
eval-feia run --prompt-file examples/prompt.md --repo . --command bash
eval-feia list --limit 5
eval-feia list --output-dir ./custom-runs
eval-feia ls --json
eval-feia results list
eval-feia results show <run-id>
eval-feia results path <run-id>
eval-feia results cat <run-id> output.txt
eval-feia clean .eval-feia/runs/<run-id>/manifest.json
```

Each `run` also writes a durable result record under `$HOME/.eval-feia/results/runs/<run-id>`
and appends `$HOME/.eval-feia/results/index.jsonl`. Set `EVAL_FEIA_RESULTS_DIR` to use a
different results root. `clean` keeps these stored results by default; use `eval-feia clean
--results` only when you intentionally want to remove the stored results root.

A run can define one human-readable label used in run-level logs and summaries:

```bash
eval-feia run "..." --label "command body test"
```

Generated worktrees are grouped by run ID and candidate ID, while the created Git branch
names include the run ID to avoid cross-run collisions. `result.json` / `run-summary.json`
record the created branch, base ref, and base SHA.

Use `eval-feia list` or the equivalent `eval-feia ls` alias to inspect saved run results
under the configured run output root before choosing a manifest for `clean`:

```text
RUN                      CREATED                    MODIFIED                   LABEL       BRANCH                         OUTPUT                         RESULT
20260514-123456-a1b2c3   2026-05-14T12:34:56+09:00 2026-05-14T12:40:00+09:00 command run eval/20260514-a1b2/cand-001 /repo/.eval-feia/runs/...     /repo/.eval-feia/runs/.../run-summary.json
```

`--output-dir <path>` inspects a custom run output root, `--limit <n>` shows only the most recent runs, and `--json` prints the same list as a JSON array.

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
- Sends worktree directory context on every worktree-specific opencode request.
- Uses `directory=<encoded-path>` for `GET`/`HEAD` and `x-opencode-directory` for non-GET requests.
- Creates worktrees, executes, collects, validates, summarizes, and prints the final result from `run`.
- Lists saved run results read-only with `list` and the `ls` alias.
- Deletes only manifest-recorded generated resources from default `clean`; stored results are removed only with `clean --results`.

See `docs/` for the full product, REST, CLI, safety, and testing specs.
