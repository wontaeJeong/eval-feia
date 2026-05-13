# OpenCode API Reference

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

## Source

This document summarizes the OpenCode server API surface required by eval-feia.

Primary source:

- `https://opencode.ai/docs/server/`

The OpenCode server documentation says `opencode serve` runs a headless HTTP server and exposes an OpenAPI endpoint. The server publishes the OpenAPI 3.1 spec at `/doc`.

Always verify the live server API at:

```text
http://<hostname>:<port>/doc
```

## Serve command

Expected invocation:

```bash
bunx -p opencode-ai@<version> opencode serve --hostname 127.0.0.1 --port <port>
```

The harness must use a command builder. Do not call a global `opencode` binary directly.

## Authentication

Set:

```bash
OPENCODE_SERVER_USERNAME=opencode
OPENCODE_SERVER_PASSWORD=<generated-password>
```

Use HTTP Basic Auth for all requests, including SSE.

## Required API endpoints

| Area | Method | Path |
|---|---:|---|
| Health | GET | `/global/health` |
| Global SSE | GET | `/global/event` |
| Server SSE | GET | `/event` |
| Project | GET | `/project/current` |
| Path | GET | `/path` |
| VCS | GET | `/vcs` |
| Session list | GET | `/session` |
| Session create | POST | `/session` |
| Session status | GET | `/session/status` |
| Session detail | GET | `/session/:id` |
| Children | GET | `/session/:id/children` |
| Todo | GET | `/session/:id/todo` |
| Diff | GET | `/session/:id/diff` |
| Message list | GET | `/session/:id/message` |
| Message send | POST | `/session/:id/message` |
| Prompt async | POST | `/session/:id/prompt_async` |
| File status | GET | `/file/status` |
| File content | GET | `/file/content` |
| OpenAPI doc | GET | `/doc` |

## Health response

Expected shape:

```json
{
  "healthy": true,
  "version": "1.4.6"
}
```

The harness must treat missing version as `unknown`.

## Path response

Use `/path` first for cwd verification.

The exact schema can vary. Search these fields:

- `cwd`
- `path`
- `root`
- `directory`
- `project.path`
- `project.root`
- `project.directory`

Do not force success from ambiguous data.

## Project fallback

If `/path` cannot prove cwd, call `/project/current`.

Search the same path-like fields.

## Session creation

Request:

```http
POST /session
```

Body:

```json
{
  "title": "eval-feia run-001"
}
```

The response must provide a session ID.

## Prompt submission

Prefer async prompt submission:

```http
POST /session/:id/prompt_async
```

Use the same body semantics as `/session/:id/message`.

Prompt submission is forbidden until SSE is connected.

## SSE event handling

Allowed streams:

- `/global/event`
- `/event`

SSE parser must support:

- `event:` lines
- `data:` lines
- multi-line data
- comments
- keepalive lines
- blank-line event boundaries

Unknown event types must be logged, not discarded.

## Polling endpoints

SSE is primary for live trajectory. Polling fills gaps.

Poll:

- `/session/status`
- `/session/:id/children`
- `/session/:id/todo`

Default interval: 1 to 2 seconds.

## Runtime guard usage

Use endpoints in this order:

1. `/global/health`
2. `/path`
3. `/project/current` only if needed
4. `/session`
5. SSE stream
6. `/session/:id/prompt_async`
7. status/children/todo polling
