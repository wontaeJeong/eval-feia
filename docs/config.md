# Configuration

## Example `eval-feia.yaml`

```yaml
server:
  url: "http://127.0.0.1:4096"
  username: null
  password_env: null
  health_retries: 10
  health_interval_ms: 500

repo:
  path: "."
  base_ref: "HEAD"
  worktree_root: ".eval-feia/worktrees"

run:
  output_root: ".eval-feia/runs"
  candidates: 3
  concurrency: 1
  timeout_seconds: 3600
  prompt_file: "./prompt.md"
  agent: "build"
  model: null
  delete_sessions_after_collect: false

validation:
  commands:
    - name: "unit-tests"
      command: "pytest -q"
      timeout_seconds: 600
      required: true

summary:
  include_full_diff: false
  include_messages: true
  include_child_sessions: true
```

## Server config

### `server.url`

The base URL of the externally started opencode server.

### `server.username`, `server.password_env`

Optional HTTP basic auth support. If `OPENCODE_SERVER_PASSWORD` protects the server, set `password_env` to the environment variable that contains the password. Do not store the password directly in config files.

### `server.health_retries`, `server.health_interval_ms`

Preflight retry policy for `GET /global/health`.

## Repo config

### `repo.path`

Path to the git repository.

### `repo.base_ref`

Base commit/ref for generating worktrees.

### `repo.worktree_root`

Root directory for generated git worktrees.

## Run config

### `run.candidates`

Number of worktrees/candidates to create.

### `run.concurrency`

Bounded concurrency. Start with `1` in MVP.

### `run.timeout_seconds`

Per-candidate timeout.

### `run.agent`

Optional opencode agent name passed in the message body. Example: `build`, `plan`, or a custom agent.

### `run.model`

Optional explicit model object:

```yaml
model:
  providerID: "anthropic"
  modelID: "claude-sonnet-4-5"
```

If omitted, opencode chooses the configured default.

## Validation config

Validation commands are executed locally by `eval-feia` inside each worktree after opencode returns.

Each command records:

- command string
- cwd
- start/end time
- exit code
- stdout path
- stderr path
- timeout flag

## Path normalization

All configured paths should be resolved to absolute paths before use. Directory values sent to opencode must be URL-encoded exactly once.
