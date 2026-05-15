# OpenCode REST API Reference for eval-feia

This document captures the opencode HTTP API surface needed by `eval-feia`, plus the broader API groups exposed by current opencode docs and generated SDK source.

Runtime source of truth: the running server publishes an OpenAPI 3.1 spec at:

```text
http://<hostname>:<port>/doc
```

Use this endpoint to confirm exact request/response schemas for the installed opencode version.

## Server basics

Start a standalone server externally:

```bash
opencode serve --hostname 127.0.0.1 --port 4096
```

Default port: `4096`.

Optional server authentication:

```bash
OPENCODE_SERVER_PASSWORD=your-password opencode serve
```

When protected, use HTTP basic auth. The default username is `opencode` unless `OPENCODE_SERVER_USERNAME` is set.

## Directory context

`eval-feia` must run each candidate against a different worktree. opencode supports directory context through request metadata.

Recommended client rule:

- Non-GET/HEAD: send header `x-opencode-directory: <url-encoded-absolute-worktree-path>`.
- GET/HEAD: send query parameter `directory=<url-encoded-absolute-worktree-path>`.

Why this rule: the official JS SDK accepts a `directory` option, stores it as an encoded `x-opencode-directory` header, and rewrites GET/HEAD requests to use the `directory` query parameter while removing the header.

Implementation rules:

1. Resolve the worktree path to an absolute path.
2. URL-encode it exactly once.
3. Do not send raw CJK/non-ASCII paths in the header.
4. On Windows, normalize backslashes or use forward-slash path form before encoding.
5. After session creation, verify the returned session directory when available.

Example non-GET:

```bash
curl -X POST "http://127.0.0.1:4096/session"   -H "Content-Type: application/json"   -H "x-opencode-directory: %2Fhome%2Fme%2Frepo%2F.eval-feia%2Fworktrees%2Fcand-001"   -d '{"title":"eval-feia/run-001/cand-001"}'
```

Example GET:

```bash
curl "http://127.0.0.1:4096/path?directory=%2Fhome%2Fme%2Frepo%2F.eval-feia%2Fworktrees%2Fcand-001"
```

## MVP REST flow

### 1. Health check

```http
GET /global/health
```

Expected response shape:

```json
{ "healthy": true, "version": "..." }
```

### 2. Verify effective path

```http
GET /path?directory=<encoded-worktree>
GET /project/current?directory=<encoded-worktree>
GET /config?directory=<encoded-worktree>
GET /vcs?directory=<encoded-worktree>
```

Use these to verify opencode can resolve the worktree context and read worktree-local configuration.

### 3. Create session

```http
POST /session
x-opencode-directory: <encoded-worktree>
Content-Type: application/json
```

Body:

```json
{
  "title": "eval-feia/<run-id>/<candidate-id>"
}
```

Response: `Session`.

Important fields commonly used by eval-feia:

```json
{
  "id": "ses_...",
  "directory": "...",
  "title": "...",
  "version": "...",
  "parentID": null
}
```

### 4. Send prompt and wait synchronously

```http
POST /session/{id}/message
x-opencode-directory: <encoded-worktree>
Content-Type: application/json
```

Body:

```json
{
  "agent": "build",
  "model": {
    "providerID": "anthropic",
    "modelID": "claude-sonnet-4-5"
  },
  "parts": [
    {
      "type": "text",
      "text": "<prompt text>"
    }
  ]
}
```

Fields are optional except `parts`. Omit `model` to use opencode defaults. Omit `agent` to use opencode defaults.

Use this synchronous endpoint as the MVP default. It sends a message and waits for the response.

### 5. Optional slash command execution

```http
POST /session/{id}/command
x-opencode-directory: <encoded-worktree>
Content-Type: application/json
```

Body:

```json
{
  "agent": "build",
  "model": "anthropic/claude-sonnet-4-5",
  "command": "bash",
  "arguments": "<prompt text>"
}
```

Fields are optional except `command` and `arguments`. Do not send `parts`, `noReply`, `system`, or `tools` to this endpoint. If a user enters `/bash`, send `"bash"` as the command value.

### 6. Optional async prompt

```http
POST /session/{id}/prompt_async
x-opencode-directory: <encoded-worktree>
Content-Type: application/json
```

Body is the same as `/session/{id}/message`. Response is `204 No Content`.

Do not use this as the MVP default unless `/event` or `/session/status` handling is implemented robustly. Async execution requires reliable progress tracking, timeout handling, permission handling, and child-session tracking.

### 7. Track status

```http
GET /session/status?directory=<encoded-worktree>
```

Response shape:

```json
{
  "ses_...": { "type": "idle" }
}
```

Known status variants from generated types include:

```text
idle
busy
retry
```

### 8. Stream events

Instance events:

```http
GET /event?directory=<encoded-worktree>
Accept: text/event-stream
```

Global events:

```http
GET /global/event
Accept: text/event-stream
```

Useful event types include:

- `session.created`
- `session.updated`
- `session.deleted`
- `session.status`
- `session.idle`
- `session.diff`
- `session.error`
- `message.updated`
- `message.part.updated`
- `permission.updated`
- `permission.replied`
- `todo.updated`
- `file.edited`

MVP can rely on synchronous `/message` by default, or synchronous `/command` when command mode is configured, and use polling for collection. SSE can be added for progress display and async mode.

### 9. Permission handling

```http
POST /session/{id}/permissions/{permissionID}
x-opencode-directory: <encoded-worktree>
Content-Type: application/json
```

Body:

```json
{
  "response": "allow",
  "remember": false
}
```

Recommended MVP policy: avoid interactive permission waits by configuring opencode permissions appropriately for disposable worktrees. If a permission event appears and no auto-permission policy is configured, mark candidate as `permission_required` and abort or fail clearly.

### 10. Collect results

```http
GET /session/{id}?directory=<encoded-worktree>
GET /session/{id}/message?directory=<encoded-worktree>
GET /session/{id}/children?directory=<encoded-worktree>
GET /session/{id}/todo?directory=<encoded-worktree>
GET /session/{id}/diff?directory=<encoded-worktree>
GET /file/status?directory=<encoded-worktree>
```

For child sessions, recursively collect:

```http
GET /session/{childID}?directory=<encoded-worktree>
GET /session/{childID}/message?directory=<encoded-worktree>
GET /session/{childID}/children?directory=<encoded-worktree>
GET /session/{childID}/diff?directory=<encoded-worktree>
```

### 11. Abort on timeout

```http
POST /session/{id}/abort
x-opencode-directory: <encoded-worktree>
```

Call this when a candidate exceeds its timeout.

## Full endpoint inventory

The following endpoint groups are available in current opencode docs and generated SDK source. Confirm against `/doc` for the installed version.

### Global

| Method | Path | Purpose |
|---|---|---|
| GET | `/global/health` | Server health and version |
| GET | `/global/event` | Global SSE event stream |

### Project

| Method | Path | Purpose |
|---|---|---|
| GET | `/project` | List all projects |
| GET | `/project/current` | Get current project |

### PTY

The generated SDK exposes PTY endpoints. They are not needed for eval-feia MVP.

| Method | Path | Purpose |
|---|---|---|
| GET | `/pty` | List PTY sessions |
| POST | `/pty` | Create PTY session |
| GET | `/pty/{id}` | Get PTY session info |
| PUT | `/pty/{id}` | Update PTY session |
| DELETE | `/pty/{id}` | Remove PTY session |
| GET | `/pty/{id}/connect` | Connect to PTY session, typically WebSocket/streaming behavior |

### Path and VCS

| Method | Path | Purpose |
|---|---|---|
| GET | `/path` | Get current path info |
| GET | `/vcs` | Get VCS info for current project |

### Instance

| Method | Path | Purpose |
|---|---|---|
| POST | `/instance/dispose` | Dispose current instance |

Do not call this in MVP. The evaluator does not own server or instance lifecycle.

### Config

| Method | Path | Purpose |
|---|---|---|
| GET | `/config` | Get config info |
| PATCH | `/config` | Update config |
| GET | `/config/providers` | List providers and default models |

### Provider

| Method | Path | Purpose |
|---|---|---|
| GET | `/provider` | List providers |
| GET | `/provider/auth` | Get provider auth methods |
| POST | `/provider/{id}/oauth/authorize` | Start provider OAuth authorize |
| POST | `/provider/{id}/oauth/callback` | Complete provider OAuth callback |

### Sessions

| Method | Path | Purpose |
|---|---|---|
| GET | `/session` | List sessions |
| POST | `/session` | Create session |
| GET | `/session/status` | Get status for all sessions |
| GET | `/session/{id}` | Get session details |
| DELETE | `/session/{id}` | Delete session and data |
| PATCH | `/session/{id}` | Update session properties |
| GET | `/session/{id}/children` | Get child sessions |
| GET | `/session/{id}/todo` | Get todo list |
| POST | `/session/{id}/init` | Analyze app and create AGENTS.md |
| POST | `/session/{id}/fork` | Fork session at message |
| POST | `/session/{id}/abort` | Abort running session |
| POST | `/session/{id}/share` | Share session |
| DELETE | `/session/{id}/share` | Unshare session |
| GET | `/session/{id}/diff` | Get session diff |
| POST | `/session/{id}/summarize` | Summarize session |
| POST | `/session/{id}/revert` | Revert a message |
| POST | `/session/{id}/unrevert` | Restore reverted messages |
| POST | `/session/{id}/permissions/{permissionID}` | Respond to permission request |

### Messages

| Method | Path | Purpose |
|---|---|---|
| GET | `/session/{id}/message` | List messages in session |
| POST | `/session/{id}/message` | Send message and wait for response |
| GET | `/session/{id}/message/{messageID}` | Get message details |
| POST | `/session/{id}/prompt_async` | Send message asynchronously |
| POST | `/session/{id}/command` | Execute slash command |
| POST | `/session/{id}/shell` | Run shell command |

### Commands

| Method | Path | Purpose |
|---|---|---|
| GET | `/command` | List commands |

### Files and search

| Method | Path | Purpose |
|---|---|---|
| GET | `/find?pattern=<pat>` | Search text in files |
| GET | `/find/file?query=<q>` | Find files/directories by name |
| GET | `/find/symbol?query=<q>` | Find workspace symbols |
| GET | `/file?path=<path>` | List files/directories |
| GET | `/file/content?path=<p>` | Read file |
| GET | `/file/status` | Get tracked file status |

`/find/file` query parameters include `query`, `type`, `directory`, `limit`, and legacy `dirs`.

### Tools

Experimental.

| Method | Path | Purpose |
|---|---|---|
| GET | `/experimental/tool/ids` | List tool IDs |
| GET | `/experimental/tool?provider=<p>&model=<m>` | List tools with JSON schemas |

### LSP, formatter, MCP

| Method | Path | Purpose |
|---|---|---|
| GET | `/lsp` | Get LSP server status |
| GET | `/formatter` | Get formatter status |
| GET | `/mcp` | Get MCP server status |
| POST | `/mcp` | Add MCP server dynamically |
| POST | `/mcp/{name}/connect` | Connect MCP server; generated SDK |
| POST | `/mcp/{name}/disconnect` | Disconnect MCP server; generated SDK |
| DELETE | `/mcp/{name}/auth` | Remove MCP OAuth credentials; generated SDK |
| POST | `/mcp/{name}/auth` | Start MCP OAuth flow; generated SDK |
| POST | `/mcp/{name}/auth/callback` | Complete MCP OAuth callback; generated SDK |
| POST | `/mcp/{name}/auth/authenticate` | Start OAuth and wait for callback; generated SDK |

### Agents and logging

| Method | Path | Purpose |
|---|---|---|
| GET | `/agent` | List available agents |
| POST | `/log` | Write log entry |

### TUI

Not needed for eval-feia MVP.

| Method | Path | Purpose |
|---|---|---|
| POST | `/tui/append-prompt` | Append text to prompt |
| POST | `/tui/open-help` | Open help dialog |
| POST | `/tui/open-sessions` | Open session selector |
| POST | `/tui/open-themes` | Open theme selector |
| POST | `/tui/open-models` | Open model selector |
| POST | `/tui/submit-prompt` | Submit current prompt |
| POST | `/tui/clear-prompt` | Clear prompt |
| POST | `/tui/execute-command` | Execute TUI command |
| POST | `/tui/show-toast` | Show toast |
| POST | `/tui/publish` | Publish TUI event; generated SDK |
| GET | `/tui/control/next` | Wait for next control request |
| POST | `/tui/control/response` | Respond to control request |

### Auth

| Method | Path | Purpose |
|---|---|---|
| PUT | `/auth/{id}` | Set provider authentication credentials |

Do not use this in MVP unless explicitly asked. Credential management is out of scope.

### Events

| Method | Path | Purpose |
|---|---|---|
| GET | `/event` | Instance SSE event stream |
| GET | `/global/event` | Global SSE event stream |

### Docs

| Method | Path | Purpose |
|---|---|---|
| GET | `/doc` | OpenAPI 3.1 specification HTML/spec page |

## Recommended MVP endpoint subset

Only these endpoints are required for the first working version:

```text
GET  /global/health
GET  /path
GET  /project/current
GET  /config
GET  /vcs
POST /session
GET  /session/status
GET  /session/{id}
POST /session/{id}/message
POST /session/{id}/command   optional slash-command execution
POST /session/{id}/abort
GET  /session/{id}/message
GET  /session/{id}/children
GET  /session/{id}/todo
GET  /session/{id}/diff
GET  /file/status
GET  /event              optional progress mode
POST /session/{id}/permissions/{permissionID} optional permission mode
```

## Important implementation cautions

1. Do not implement `/attach`. It is not a REST endpoint. Attach is a client behavior.
2. Do not use `opencode run --attach` in MVP.
3. Do not default to `prompt_async` until event/status handling is robust.
4. Do not call `/instance/dispose` from eval-feia MVP.
5. Do not call auth endpoints or print credential payloads.
6. Do not assume server process cwd equals candidate cwd. The request directory context is the effective cwd.
7. Confirm exact schemas from `/doc` in integration tests when opencode is available.
