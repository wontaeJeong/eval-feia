# Prompt 05: Live UX and SSE

Implement real-time trajectory output.

Requirements:

- connect SSE before prompt
- parser handles event/data/multiline/blank lines
- prompt send must not block renderer
- Rich table live mode
- JSONL progress mode
- no-live mode
- poll status/children/todo
- update message/tool/child/todo counters
- show idle-wait phase

Add tests for live updates and JSONL flushing.
