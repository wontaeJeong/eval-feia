# AGENTS

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Role

You are an implementation agent for `eval-feia`.

Build the project from zero using the docs in this repository.

## Ground rules

- Do not assume existing code.
- Read `PRD.md`, `REQUIREMENTS.md`, and `ARCHITECTURE.md` before coding.
- Keep the implementation small but complete.
- Write tests as you implement.
- Never call a global `opencode` binary directly.
- Use version-pinned `bunx -p opencode-ai@<version>`.
- Bind OpenCode to `127.0.0.1`.
- Use `OPENCODE_SERVER_PASSWORD`.
- Do not log secrets.
- Print worktree paths immediately.
- Print actual served server info.
- Restart on version/cwd mismatch.
- Connect SSE before prompt submission.
- Keep Rich table cells short.
- Use JSONL for machine-readable mode.

## Preferred package layout

```text
src/eval_feia/
  __init__.py
  cli.py
  models.py
  orchestrator.py
  worktree.py
  process.py
  opencode_client.py
  sse.py
  live.py
  metrics.py
  validation.py
  reports.py
  cleanup.py
tests/
```

## Commands

Run tests with:

```bash
uv run pytest
```

Run a single local batch with:

```bash
uv run eval-feia run --repo . --count 1 --concurrency 1 --opencode-version 1.4.6 --json
```

## Completion report

When done, report:

- changed files
- implemented commands/options
- tests added
- test results
- known limitations
