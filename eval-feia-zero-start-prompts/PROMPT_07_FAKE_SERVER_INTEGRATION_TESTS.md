# Prompt 07: Fake OpenCode Server Integration Tests

Build fake OpenCode server tests.

Fake endpoints:

- `/global/health`
- `/path`
- `/project/current`
- `/session`
- `/global/event` or `/event`
- `/session/status`
- `/session/:id/children`
- `/session/:id/todo`
- `/session/:id/prompt_async`

Test:

- happy path
- health timeout
- cwd mismatch
- version mismatch restart
- SSE before prompt
- live output updates
- idle completion
