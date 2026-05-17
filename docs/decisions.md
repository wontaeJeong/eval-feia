# Architectural Decisions

## ADR-001: Server lifecycle is external

Decision: `eval-feia` does not start or kill `opencode serve` in MVP.

Rationale: server startup, model credentials, and local opencode config are separate operational concerns. Keeping them external reduces hidden side effects and makes failures easier to diagnose.

## ADR-002: REST-first implementation

Decision: `eval-feia` uses opencode REST/SSE APIs directly instead of shelling out to `opencode run --attach`.

Rationale: evaluator correctness depends on explicit control over sessions, directory context, timeouts, artifact collection, child sessions, and final summaries.

## ADR-003: Synchronous message endpoint by default

Decision: MVP uses `POST /session/{id}/message` by default, not `POST /session/{id}/prompt_async`.

Rationale: the synchronous endpoint sends a message and waits for a response. Async mode requires robust event/status tracking and is better added after the base runner is stable.

## ADR-004: Minimal command surface

Decision: MVP exposes `run`, read-only `list` / `ls`, `clean`, and read-only `results` inspection commands.

Rationale: `run` already includes execution, collection, and summary. `list` / `ls` discover saved run artifacts so users can inspect past generated outputs and choose a manifest for `clean`; `results` reads the durable local file-backed history without contacting opencode.

## ADR-005: Manifest-based cleanup

Decision: default `clean` removes only generated resources recorded in the manifest; stored result history cleanup is a separate explicit `clean --results` action against a validated eval-feia results root.

Rationale: worktree cleanup is destructive. Manifest-based cleanup prevents accidental deletion of unrelated files or server processes, while stored result history has a separate ownership marker and explicit cleanup path.

## ADR-006: Directory context must be explicit per request

Decision: Every worktree-specific request carries a directory context.

Rationale: the server process cwd is not sufficient when one server handles multiple worktrees. The effective working directory must be request-specific.
