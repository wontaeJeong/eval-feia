# Troubleshooting

## `OpenCode returned HTTP 400 for /session`

Likely causes:

1. Missing or malformed `x-opencode-directory` header.
2. Directory value was not URL-encoded.
3. Directory was encoded twice.
4. Directory does not exist on the server machine.
5. The body does not match the installed opencode `/session` schema.
6. Server requires basic auth and the request omitted credentials.

Debug steps:

```bash
curl http://127.0.0.1:4096/global/health

curl "http://127.0.0.1:4096/path?directory=<encoded-worktree>"

curl -X POST "http://127.0.0.1:4096/session"   -H "Content-Type: application/json"   -H "x-opencode-directory: <encoded-worktree>"   -d '{"title":"debug"}'
```

## Session created in wrong directory

Check that GET requests use `directory` query and POST requests use `x-opencode-directory` header. Do not rely on the server process cwd.

## Run hangs

Likely causes:

- prompt was sent with `prompt_async` but status/event handling is incomplete
- permission request is waiting
- provider request is stuck
- child session/subtask is still busy

MVP mitigation:

- use synchronous `/session/{id}/message`
- enforce per-candidate timeout
- abort on timeout
- collect partial artifacts

## No final output

Check `messages.json` and message parts. The final assistant output may be in a text part of the last assistant message. If structured output is needed later, confirm the installed version's `/doc` schema for structured output fields.

## Clean refuses to delete

This is intentional when a path fails safety checks. Inspect `manifest.json` and use `--dry-run` to see planned actions.
