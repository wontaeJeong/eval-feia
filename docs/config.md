# Runtime Configuration

The MVP CLI is arguments-only. It does not load YAML, JSON, or TOML config files and does not expose a `--config` flag.

`eval-feia run` maps CLI input into the internal `EvalConfig` model, then resolves every path to an absolute path before creating worktrees or sending directory context to opencode.

## CLI Inputs

- `PROMPT`: inline prompt text.
- `--prompt-file PATH`: prompt file; mutually exclusive with `PROMPT`.
- `--server-url URL`: externally started opencode server. Defaults to `http://127.0.0.1:4096`.
- `--repo PATH`: git repository path. Defaults to the current directory.
- `--branch REF`: base ref for generated worktrees. Defaults to `HEAD`.
- `--attempts N`: number of candidates to run. Defaults to `1`.
- `--label TEXT`: run-level human-readable label used in logs, stored results, summaries, and indexed listings.
- `--command NAME`: optional opencode slash command. A leading slash is accepted and stripped before sending the HTTP request body.
- `--base-dir PATH`: eval-feia state base. `output/`, `worktrees/`, `results/`, and the default SQLite DB are derived from it per run.
- `--output-dir PATH`: generated run artifact base. Defaults to `<base>` and writes each run under `<base>/<run-id>/output`; `list` accepts the same flag to inspect custom roots. It cannot be combined with `--base-dir`.

## Environment Inputs

`EVAL_FEIA_BASE_DIR` sets the shared eval-feia state base. When unset, the base defaults to `$HOME/.eval-feia`. Stored result records default to `<base>/<run-id>/results` and can be overridden with `EVAL_FEIA_RESULTS_DIR` when durable results must intentionally live outside the per-run base layout.

The SQLite metadata index defaults to `<base>/eval-feia.sqlite3`. Set `EVAL_FEIA_DB_PATH` to use a custom database path. Custom DB paths are used for indexing and listing but are not deleted by `clean --delete-index`.

## Listing Configuration

`eval-feia list` reads generated run artifact directories by default. It switches to the SQLite metadata index when `EVAL_FEIA_DB_PATH` is set or when one of these filters is supplied:

- `--status pending|running|success|failed|cancelled`
- `--branch REF`
- `--label TEXT`

`--limit`, `--base-dir`, `--output-dir`, and `--json` apply to both listing modes.

## Internal Model

The code still uses typed Pydantic models for server, repo, run, validation, summary, and manifest data. Programmatic callers and tests may construct `EvalConfig` directly, while the CLI keeps the compact `run`, `list`, `results`, and `clean` command surface.

Server health preflight defaults to 10 attempts, 500ms between attempts, and a dedicated 2s timeout per `GET /global/health` request.

## Path Normalization

All configured paths are resolved to absolute paths before use. Directory values sent to opencode must be URL-encoded exactly once.
