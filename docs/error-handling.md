# Error Handling

## Server unavailable

When `GET /global/health` fails after configured retries, stop before creating worktrees.

Message should include:

- server URL
- number of attempts
- last status/error
- suggested command to start server

## Directory context mismatch

After creating a session, inspect the response. If it includes `directory` and it does not match the expected worktree, fail that candidate before sending the prompt.

Do not continue execution in the wrong directory.

## Prompt failure

If the execution request returns a non-2xx response (`/session/{id}/message` by default, or `/session/{id}/command` when command mode is configured):

1. Save the response body to `error.json`.
2. Attempt to collect session state if a session ID exists.
3. Mark candidate `prompt_failed`.

## Timeout

If a candidate exceeds `timeout_seconds`:

1. Send `POST /session/{id}/abort`.
2. Poll `/session/status` briefly.
3. Collect available messages/diff.
4. Mark candidate `timeout`.

## Permission required

If SSE or message parts show a permission request and no auto-permission policy is configured, do not hang indefinitely.

Recommended behavior:

- mark candidate `permission_required`
- abort session
- write the permission metadata to `error.json`

Auto-approval can be added later, but only for disposable worktrees and explicit config.

## Collection failure

Collection is best-effort after a prompt failure or timeout. Save partial results and include missing artifacts in the candidate summary.

## Cleanup safety failure

`clean-run-artifacts` should refuse to delete when:

- manifest is missing or invalid
- path is empty, `/`, home directory, or repo root
- path is not under expected generated root and not a known git worktree from manifest
- path is a symlink escaping the allowed root

## Interruption

On Ctrl-C:

1. Stop scheduling new candidates.
2. Abort currently running sessions where possible.
3. Flush manifest.
4. Write partial summary.
5. Exit with `130`.
