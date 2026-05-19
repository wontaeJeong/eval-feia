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
- `--label TEXT`: run-level human-readable label used in logs, stored results, summaries, and listings.
- `--command NAME`: optional opencode slash command. A leading slash is accepted and stripped before sending the HTTP request body.
- `--progress / --no-progress`: enable or disable live progress logs, including opencode event stream updates. Progress is enabled by default.
- `--quiet`: hide progress logs while keeping final output.
- `--base-dir PATH`: eval-feia state base. `output/`, `worktrees/`, and `results/` are derived from it per run.
- `--output-dir PATH`: generated run artifact base. Defaults to `<base>` and writes each run under `<base>/<run-id>/output`; `list` accepts the same flag to inspect custom roots. It cannot be combined with `--base-dir`.

## Environment Inputs

`EVAL_FEIA_BASE_DIR` sets the shared eval-feia state base. When unset, the base defaults to `$HOME/.eval-feia`. Stored result records default to `<base>/<run-id>/results` and can be overridden with `EVAL_FEIA_RESULTS_DIR` when durable results must intentionally live outside the per-run base layout.

## Listing Configuration

`eval-feia list` reads generated run artifact directories and stored result metadata from local files. These filters are file-backed:

- `--status pending|running|success|failed|cancelled`
- `--branch REF`
- `--label TEXT`

`--limit`, `--base-dir`, `--output-dir`, and `--json` apply to the same unified listing mode.

## Internal Model

The code still uses typed Pydantic models for server, repo, run, validation, summary, and manifest data. Programmatic callers and tests may construct `EvalConfig` directly, while the CLI keeps the compact `run`, `list`, `results`, and `clean` command surface.

Server health preflight defaults to 10 attempts, 500ms between attempts, and a dedicated 2s timeout per `GET /global/health` request.

## Path Normalization

All configured paths are resolved to absolute paths before use. Directory values sent to opencode must be URL-encoded exactly once.
