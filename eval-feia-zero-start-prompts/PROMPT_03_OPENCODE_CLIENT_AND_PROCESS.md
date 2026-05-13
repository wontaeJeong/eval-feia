# Prompt 03: Implement OpenCode Process and HTTP Client

Implement version-pinned process launch and HTTP client.

Command must be equivalent to:

```bash
bunx -p opencode-ai@<version> opencode serve --hostname 127.0.0.1 --port <port>
```

Implement:

- command builder
- process group launch
- terminate/kill
- Basic Auth
- `/global/health`
- `/path`
- `/project/current`
- `/session`
- `/session/:id/prompt_async`
- `/session/status`
- `/session/:id/children`
- `/session/:id/todo`
- SSE connection

Add unit tests with mocks.
