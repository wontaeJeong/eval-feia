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

Decision: MVP exposes a compact command surface: `run`, read-only `result`, and manifest/results cleanup through `clean`.

Rationale: `run` already includes execution, collection, and summary. `result` discovers generated run artifacts, stored result metadata, and individual durable result files without contacting opencode. `clean` keeps destructive behavior explicit with either a manifest argument or `--results`.

## ADR-005: Manifest-based cleanup

Decision: default `clean <manifest>` removes only generated resources recorded in the manifest; stored result history cleanup requires an explicit `clean --results` action against a validated eval-feia results root.

Rationale: worktree cleanup is destructive. Manifest-based cleanup prevents accidental deletion of unrelated files or server processes, while stored result history has a separate ownership marker and explicit cleanup path.

## ADR-006: Directory context must be explicit per request

Decision: Every worktree-specific request carries a directory context.

Rationale: the server process cwd is not sufficient when one server handles multiple worktrees. The effective working directory must be request-specific.

## ADR-007: File-backed metadata stays authoritative

Decision: generated artifacts and durable stored-result files remain authoritative. Listing and filtering read those files directly instead of using a separate metadata store.

Rationale: large logs and opencode payloads are already files. Keeping listing file-backed avoids a second source of truth and keeps cleanup manifest-based.
