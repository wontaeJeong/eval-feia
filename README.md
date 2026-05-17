# eval-feia

`eval-feia` is a local, REST-only CLI evaluator for running opencode coding experiments across isolated git worktrees.

The server lifecycle stays external: start `opencode serve` yourself, then run evaluations against that HTTP endpoint. The MVP exposes `run`, `list`/`ls`, and `clean`.

```bash
eval-feia run "Fix the issue described in README" --repo . --branch HEAD --attempts 1
eval-feia run --prompt-file examples/prompt.md --repo . --command bash
eval-feia list --limit 10
eval-feia clean .eval-feia/runs/<run-id>/manifest.json
```

A run can define one human-readable label used in run-level logs and summaries:

```bash
eval-feia run "..." --label "command body test"
```

Generated worktrees are grouped by run ID and candidate ID, while the created Git branch
names include the run ID to avoid cross-run collisions. `result.json` / `run-summary.json`
record the created branch, base ref, and base SHA.

## Local Metadata Index

Run artifacts are still written as files under the output root. SQLite is used only as a local metadata index for querying run IDs, status, labels, paths, timing, and summary locations; large stdout/stderr logs stay in files.

By default the database is `<output-root>/eval-feia.sqlite3`, which is `.eval-feia/runs/eval-feia.sqlite3` for the default output root. Override it with `EVAL_FEIA_DB_PATH`:

```bash
EVAL_FEIA_DB_PATH=/tmp/eval-feia.sqlite3 eval-feia list --json
eval-feia ls --status success --branch HEAD --limit 5
```

`clean` keeps DB records by default and marks deleted file outputs as missing. Use `clean --db` only when you also want to delete the default SQLite index database under that output root; custom `EVAL_FEIA_DB_PATH` databases must be removed manually.

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
- Creates worktrees, executes, collects, validates, summarizes, indexes metadata, and prints the final result from `run`.
- Lists recent run metadata from the local SQLite index with `list`/`ls`.
- Deletes only manifest-recorded resources from `clean`.

See `docs/` for the full product, REST, CLI, safety, and testing specs.
