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

evals:
  - id: "command-body-test"
    prompt: "Run the command body test."
    branch_name: "eval/command-body-test"
    label: "command body test"
  - id: "attach-healthcheck"
    prompt: "Run the attach healthcheck test."
    branch_name: "eval/attach-healthcheck"
    label: "attach healthcheck"

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

Number of worktrees/candidates to create when `evals` is omitted. If `evals` is present,
the eval list length is used instead.

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

### `run.prompt` / `run.prompt_file`

Global prompt text or prompt file. Eval items can override this with their own `prompt` or
`prompt_file`. Existing configs that only set `run.prompt_file` continue to work.

### `run.branch_name` / `run.label`

Optional defaults mainly for one-off CLI runs with `--branch-name` and `--label`.
`run.branch_name` is used when an eval item omits `branch_name`; `run.label` is used for
numeric `run.candidates` runs without an explicit `evals` list.

## Eval item config

Use top-level `evals` when individual evals need distinct prompts, branch names, or display
labels:

```yaml
evals:
  - id: command-body-test
    prompt: "..."
    branch_name: "eval/command-body-test"
    label: "command body test"
```

Fields:

- `id`: stable eval identifier. If omitted, eval-feia uses the index-based candidate id.
- `prompt` / `prompt_file`: eval-specific prompt source. Falls back to `run.prompt` or
  `run.prompt_file`.
- `label`: human-readable display value for logs, summaries, and result files. It is not
  used directly for shell commands, paths, or branch names.
- `branch_name`: requested Git branch name for the eval worktree.

Fallbacks:

- `label`: eval `label`, then eval `id`, then the index-based candidate id.
- `branch_name`: eval `branch_name`, then `run.branch_name`, then `eval/<safe eval id>`.
  If an eval has a `label` but no `id`, the default branch uses the safe label.

Branch names are sanitized before use: whitespace becomes `-`, invalid Git ref characters
are replaced, repeated separators are normalized, unsafe leading/trailing characters are
trimmed, and the final value is checked with `git check-ref-format --branch`. If a requested
branch or worktree path collides, eval-feia appends a numeric suffix such as `-2` and records
the resolved branch name.

Result JSON and `run-summary.json` include the actual display and branch values:

```json
{
  "eval_id": "command-body-test",
  "label": "command body test",
  "requested_branch_name": "eval/command-body-test",
  "branch_name": "eval/command-body-test-2",
  "worktree_path": "/abs/path/to/worktree"
}
```

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
