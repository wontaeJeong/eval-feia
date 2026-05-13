# Acceptance Criteria

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## MVP acceptance

The implementation is accepted when all criteria below pass.

## Functional

- `eval-feia run` creates a batch.
- Each run creates an isolated worktree.
- Worktree path is printed immediately.
- OpenCode server is launched with version-pinned bunx.
- Health check gates prompt submission.
- CWD check gates prompt submission.
- Actual served server info is printed.
- Version/cwd mismatch triggers restart.
- Mismatched server never receives prompt.
- SSE connects before prompt submission.
- Live UX updates during execution.
- JSONL mode flushes progress lines.
- Idle detection waits for children.
- Summary JSON and CSV are produced.
- Validation runs after completion.

## Testing

- Unit tests pass.
- Fake server integration tests pass.
- No unit test requires real LLM calls.
- Restart scenarios are tested.
- Live output scenarios are tested.

## Security

- Server binds to loopback.
- Password is set.
- Secrets are redacted.
- Cleanup is manifest-based.

## Documentation

- PRD exists.
- AGENTS exists.
- API reference exists.
- CLI spec exists.
- Test plan exists.
