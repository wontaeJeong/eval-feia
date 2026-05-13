# AGENTS.md

## Project identity

This repository implements `eval-feia`, a local CLI evaluator for running opencode-based coding experiments across isolated git worktrees.

The MVP is REST-only. Do not implement execution by shelling out to `opencode run --attach`. The opencode server is assumed to be started externally by the user.

## Architectural rules

1. `eval-feia` must not start, restart, dispose, or kill `opencode serve` in the MVP.
2. `eval-feia` must communicate with opencode over HTTP REST/SSE only.
3. Every opencode request that is worktree-specific must include the effective directory context.
4. For POST/PUT/PATCH/DELETE requests, send the directory context as `x-opencode-directory` with the directory URL-encoded exactly once.
5. For GET/HEAD requests, prefer a `directory` query parameter with the directory URL-encoded exactly once.
6. Use absolute paths for worktree directories.
7. Validate returned session directory/path information when available.
8. Use manifest-based cleanup only.
9. `run` must perform collection and final summary automatically.
10. Keep the CLI surface minimal: `run` and `clean` only for MVP.

## Source constraints

The implementation agent cannot assume web access. The required opencode REST API information is included in `docs/opencode-rest-api.md`. If local opencode is available during implementation, use the running server's `/doc` endpoint to confirm the installed version's OpenAPI spec.

## Preferred implementation stack

Use Python 3.11+ for the MVP.

Recommended packages:

- `typer` for CLI
- `httpx` for REST and SSE-capable streaming primitives
- `pydantic` for config and manifest schemas
- `rich` for readable terminal output
- `pytest` and `respx` or an in-process mock server for tests

The implementation should remain simple enough that replacing `httpx` or `typer` later is possible.

## Directory layout

Recommended layout:

```text
eval-feia/
  pyproject.toml
  README.md
  AGENTS.md
  src/eval_feia/
    __init__.py
    cli.py
    config.py
    manifest.py
    git_worktree.py
    opencode_client.py
    runner.py
    collector.py
    summary.py
    clean.py
    errors.py
  tests/
    test_opencode_client.py
    test_worktree.py
    test_runner.py
    test_clean.py
    fixtures/
```

## Coding standards

- Keep side effects explicit.
- Avoid global mutable state.
- Use typed dataclasses or pydantic models for config, manifest, and run result records.
- Never log secrets, Authorization headers, provider API keys, or full auth config.
- Include run IDs and candidate IDs in logs.
- All filesystem deletion must go through a manifest validation step.

## REST execution contract

For each candidate worktree:

1. Preflight effective path:
   - `GET /path?directory=<encoded-worktree>`
   - `GET /project/current?directory=<encoded-worktree>` when available
2. Create session:
   - `POST /session`
   - header: `x-opencode-directory: <encoded-worktree>`
   - body: `{ "title": "eval-feia/<run-id>/<candidate-id>" }`
3. Send prompt:
   - `POST /session/{id}/message`
   - header: `x-opencode-directory: <encoded-worktree>`
   - body includes `parts: [{ "type": "text", "text": <prompt> }]`
4. Collect:
   - `GET /session/{id}?directory=<encoded-worktree>`
   - `GET /session/{id}/message?directory=<encoded-worktree>`
   - `GET /session/{id}/children?directory=<encoded-worktree>` recursively
   - `GET /session/{id}/todo?directory=<encoded-worktree>`
   - `GET /session/{id}/diff?directory=<encoded-worktree>`
   - `GET /file/status?directory=<encoded-worktree>`
5. Validate locally:
   - run configured validation commands in the worktree
   - capture stdout/stderr/exit code
6. Write result files.

## Testing expectations

Tests must cover:

- URL encoding of directory context.
- GET query vs non-GET header behavior.
- Health preflight retry behavior.
- Session creation and prompt send request shapes.
- Timeout and abort behavior.
- Child session discovery.
- Manifest creation and cleanup safety.
- Final summary generation.

## Do not implement

Do not add these MVP commands unless explicitly requested later:

- `serve`
- `attach`
- `collect`
- `summary`
- `report`
- `status`

Their behavior is already covered by `run` or intentionally out of scope.
