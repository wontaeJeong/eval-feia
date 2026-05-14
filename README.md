# eval-feia

`eval-feia` is a local, REST-only CLI evaluator for running opencode coding experiments across isolated git worktrees.

The server lifecycle stays external: start `opencode serve` yourself, then run evaluations against that HTTP endpoint. The MVP exposes only `run` and `clean`.

```bash
eval-feia run --config examples/eval-feia.yaml
eval-feia clean --manifest .eval-feia/runs/<run-id>/manifest.json
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
- Sends worktree directory context on every worktree-specific opencode request.
- Uses `directory=<encoded-path>` for `GET`/`HEAD` and `x-opencode-directory` for non-GET requests.
- Creates worktrees, executes, collects, validates, summarizes, and prints the final result from `run`.
- Deletes only manifest-recorded resources from `clean`.

See `docs/` for the full product, REST, CLI, safety, and testing specs.
