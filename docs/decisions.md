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

Decision: MVP exposes only `run` and `clean`.

Rationale: `run` already includes collection and summary. Extra commands increase UX and state-management complexity without adding MVP value.

## ADR-005: Manifest-based cleanup

Decision: `clean` removes only resources recorded in the manifest.

Rationale: worktree cleanup is destructive. Manifest-based cleanup prevents accidental deletion of unrelated files or server processes.

## ADR-006: Directory context must be explicit per request

Decision: Every worktree-specific request carries a directory context.

Rationale: the server process cwd is not sufficient when one server handles multiple worktrees. The effective working directory must be request-specific.
