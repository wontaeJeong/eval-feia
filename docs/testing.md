# Test Plan

## Unit tests

### Directory encoding

Verify:

- absolute paths are encoded exactly once
- spaces become `%20`
- `/` becomes `%2F` in header/query value
- CJK paths are encoded and never sent raw in headers
- GET uses query `directory`
- POST uses header `x-opencode-directory`

### REST request shapes

Mock opencode server and assert:

- health preflight calls `/global/health`
- path preflight calls `/path?directory=...`
- session create calls `/session` with encoded directory header
- prompt calls `/session/{id}/message` with encoded directory header
- slash command prompt calls `/session/{id}/command` with `command` and string `arguments`
- collection calls expected GET endpoints with directory query
- abort calls `/session/{id}/abort`

### Manifest safety

Verify:

- manifest is written after worktree creation
- clean refuses unsafe paths
- clean removes only manifest paths after generated-root marker validation
- dry-run does not delete

### Run labels and branch names

Verify:

- runtime model accepts run-level `label` and eval-specific `branch_name`
- `run.candidates` plus `run.prompt_file` model inputs still work
- run label is printed and recorded once, not repeated per candidate
- missing branch names fall back to safe `eval/<run-id>/<id>` names
- sanitized branch names pass `git check-ref-format --branch`
- duplicate requested branches resolve to unique actual `branch_name` values
- candidate `result.json` and `run-summary.json` record the actual resolved branch name
- generated worktree paths use the run directory plus candidate-id leaf, not repeated base
  ref/SHA/branch metadata

### Stored results and SQLite index

Verify:

- `run-eval` creates durable metadata, output, summary, stdout, stderr, and run logs
- `list-stored-results`, `show-stored-result`, `print-stored-result-path`, and `print-stored-result-file` read stored results without contacting opencode
- SQLite schema version 1 creates `runs` and `run_events`
- SQLite list filters support status, branch, and label
- saved artifact listing backfills an empty SQLite index idempotently
- `clean-run-artifacts` requires generated-root markers and marks deleted generated outputs as missing in SQLite metadata
- `clean-run-artifacts --delete-index` deletes only the manifest-recorded default DB and rejects custom `EVAL_FEIA_DB_PATH`

### Runner behavior

Verify:

- candidate success path
- candidate prompt failure
- timeout and abort
- validation failure
- collection partial failure
- concurrent candidate isolation
- progress lines for major run phases
- plain CLI final summary output without Rich box table borders

## Integration tests with fake opencode

Implement a minimal fake server that supports:

- `GET /global/health`
- `GET /path`
- `POST /session`
- `POST /session/{id}/message`
- `POST /session/{id}/command`
- `GET /session/{id}/message`
- `GET /session/{id}/children`
- `GET /session/{id}/diff`
- `GET /file/status`

Use it to test end-to-end run behavior without real LLM calls.

## Optional integration test with real opencode

When `OPENCODE_E2E=1` is set and a local server is available:

1. Create a temporary git repo.
2. Start or require an existing opencode server.
3. Run a no-op prompt that edits a trivial file.
4. Verify session directory and collected diff.

The MVP should not require this test in normal CI.

## Manual smoke test

```bash
opencode serve --hostname 127.0.0.1 --port 4096

eval-feia run-eval --prompt-file examples/prompt.md --repo .

eval-feia list-run-artifacts

eval-feia list-run-artifacts --status success --branch HEAD

eval-feia list-stored-results

eval-feia show-stored-result <run-id>

eval-feia clean-run-artifacts .eval-feia/runs/<run-id>/manifest.json --dry-run

eval-feia clean-run-artifacts .eval-feia/runs/<run-id>/manifest.json --delete-index --dry-run

eval-feia clean-stored-results --dry-run
```
