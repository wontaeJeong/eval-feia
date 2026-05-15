# Implementation Plan

## Phase 0: Repository bootstrap

Create Python project structure:

```text
pyproject.toml
README.md
AGENTS.md
src/eval_feia/
tests/
examples/
```

Add dependencies:

```toml
dependencies = [
  "typer>=0.12",
  "httpx>=0.27",
  "pydantic>=2",
  "rich>=13"
]
```

Dev dependencies:

```toml
[project.optional-dependencies]
dev = ["pytest", "respx", "pytest-asyncio", "ruff", "mypy"]
```

## Phase 1: Runtime models and manifest

Implement:

- `config.py`
- `manifest.py`
- schema validation
- path resolution
- JSON serialization

## Phase 2: Opencode REST client

Implement `opencode_client.py`.

Required methods:

```python
health()
path(cwd)
project_current(cwd)
config(cwd)
vcs(cwd)
session_create(cwd, title)
session_get(cwd, session_id)
session_status(cwd)
session_prompt(cwd, session_id, prompt, command=None, agent=None, model=None)
session_abort(cwd, session_id)
session_messages(cwd, session_id)
session_children(cwd, session_id)
session_todo(cwd, session_id)
session_diff(cwd, session_id)
file_status(cwd)
```

Client invariant:

- GET/HEAD calls use `directory` query.
- Non-GET calls use `x-opencode-directory` header.
- Directory value is absolute and URL-encoded exactly once.

## Phase 3: Git worktree manager

Implement:

- base SHA resolution
- worktree add
- worktree remove
- local git status/diff collection

## Phase 4: Runner

Implement `run` orchestration:

- preflight server
- create run directory
- create worktrees
- execute candidates sequentially first
- add bounded concurrency after sequential path is stable
- collect results
- run validation
- write summaries

## Phase 5: Clean command

Implement manifest-based cleanup with dry-run.

Safety checks are mandatory before any deletion.

## Phase 6: Tests

Add unit tests and fake-server integration tests. Make request-shape tests strict.

## Phase 7: Documentation and examples

Add:

- `examples/prompt.md`
- README quickstart
- troubleshooting section

## MVP completion checklist

- [ ] `eval-feia run --prompt-file examples/prompt.md --repo .` works against fake server.
- [ ] Health check retry works.
- [ ] Worktree paths are printed.
- [ ] Session creation uses correct directory context.
- [ ] Prompt uses REST `/session/{id}/message`, or `/session/{id}/command` when command mode is configured.
- [ ] Results are collected and summarized automatically.
- [ ] `clean --dry-run` and `clean` work safely.
- [ ] Tests cover request context and cleanup safety.
