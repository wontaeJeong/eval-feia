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
- `--label TEXT`: run-level human-readable label used in logs and summaries.
- `--command NAME`: optional opencode slash command. A leading slash is accepted and stripped before sending the HTTP request body.
- `--output-dir PATH`: run output root. Defaults to `.eval-feia/runs`; `list` / `ls` accept the same flag to inspect custom run roots.

## Internal Model

The code still uses typed Pydantic models for server, repo, run, validation, summary, and manifest data. Programmatic callers and tests may construct `EvalConfig` directly, but the CLI surface stays minimal: `run`, read-only `list` / `ls`, and `clean`, with direct flags only.

Server health preflight defaults to 10 attempts, 500ms between attempts, and a dedicated 2s timeout per `GET /global/health` request.

## Path Normalization

All configured paths are resolved to absolute paths before use. Directory values sent to opencode must be URL-encoded exactly once.
