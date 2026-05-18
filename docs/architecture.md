# Architecture

## Core model

`eval-feia` is an orchestration layer around git worktrees and opencode's HTTP server.

```text
user-managed opencode serve
        ^
        | REST/SSE
        |
eval-feia run
        |
        +-- worktree candidate 001
        +-- worktree candidate 002
        +-- worktree candidate 003
```

The server lifecycle is external. `eval-feia` only verifies server availability and then uses REST calls with an explicit directory context.

## Why REST instead of CLI attach

REST is the correct MVP direction for this project because the evaluator needs deterministic control over:

- session creation
- request directory context
- message body shape
- timeout handling
- session status
- child session discovery
- diff and message collection
- output serialization

The CLI attach mode is useful for humans but hides several behaviors that an evaluator should own explicitly.

## Runtime components

### CLI

Parses direct arguments and calls the runner. Exposes `run`, read-only `list`, read-only `results` subcommands, and manifest/results cleanup through `clean`.

### Runtime model builder

Builds typed runtime models from CLI arguments. Resolves paths to absolute paths. Validates defaults.

### Git worktree manager

Creates and removes git worktrees. Records every generated path in the manifest.

### Opencode REST client

Wraps HTTP calls to opencode. Enforces directory context rules.

### Runner

Coordinates candidates concurrently. Owns timeout and cancellation policy.

### Collector

Fetches session data, child session data, diffs, todo state, file status, and local git diffs.

### Validator

Runs configured validation commands inside each worktree.

### Summary writer

Writes machine-readable result files and human-readable markdown summaries. Prints final console output.

### Stored results store

Writes durable run metadata, output, summary, and log files under `<base>/<run-id>/results` or `EVAL_FEIA_RESULTS_DIR`. Powers the read-only stored-result inspection commands.

### SQLite metadata index

Indexes run metadata and lifecycle events in `eval-feia.sqlite3` for filtered `list` queries. Large logs and collected opencode payloads stay in files.

### Cleaner

Removes manifest-recorded worktrees and result directories. Does not touch opencode server processes.

## Execution lifecycle

```text
build runtime config
  -> health preflight
  -> print run progress and context
  -> create run directory
  -> create worktrees
  -> for each worktree:
       verify effective opencode directory
       create session
       send prompt via POST /session/{id}/message, or /command when run.command is set
       wait for response or timeout
       collect session artifacts
       run local validators
       write candidate result
  -> write run summary
  -> print final plain result table
```

## Concurrency

MVP should support sequential execution and bounded parallel execution.

The default concurrency is `1`. Increasing concurrency is allowed in the internal model but should be bounded because multiple opencode sessions can compete for provider rate limits, filesystem IO, and CPU.

## Directory context

Directory context is the central correctness requirement.

For each worktree, every REST call must be scoped to that worktree. Use:

- `x-opencode-directory` header for non-GET/HEAD requests
- `directory` query parameter for GET/HEAD requests

The value must be the URL-encoded absolute path.

## Result directory

Recommended output layout:

```text
.eval-feia/
  20260514-123456-a1b2c3/
    output/
      manifest.json
      run-summary.md
      run-summary.json
      candidates/
        cand-001/
          worktree.txt
          session.json
          messages.json
          children.json
          todo.json
          diff.json
          file-status.json
          local-git-diff.patch
          validation.json
          final-output.md
          error.json
        cand-002/
          ...
    worktrees/
      cand-001/
      cand-002/
    results/
      index.jsonl
      metadata.json
      output.txt
  eval-feia.sqlite3
```

Generated worktrees use the matching compact per-run layout:

```text
.eval-feia/
  20260514-123456-a1b2c3/
    worktrees/
      cand-001/
      cand-002/
```

The branch carries run-scoped uniqueness (`eval/<run-id>/<candidate>`), while base ref and
base SHA stay in manifest and result metadata.

## Failure model

A candidate can fail independently. The whole run fails only when preflight fails or the tool cannot create the run manifest safely.

Candidate failure classes:

- server unavailable
- directory context mismatch
- session create failed
- prompt failed
- permission required
- timeout
- abort failed
- collection failed
- validation failed
- unexpected exception

## Safety model

The tool must be conservative with destructive actions:

- never delete a generated worktree or run artifact path not listed in the manifest, and never delete generated roots without eval-feia marker validation
- never delete stored result history unless `clean --results` is explicitly used and the target is a validated eval-feia results root
- never delete the SQLite metadata index unless `clean --delete-index` is explicitly used with a manifest that records the default DB path
- never delete the repository root
- never delete outside the configured eval-feia base unless the manifest explicitly says it is a generated git worktree
- never kill `opencode serve`
- never print auth headers or provider credentials
