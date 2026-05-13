# Prompt 08: Review and Harden

Review the full implementation.

Check:

- no global opencode call
- no prompt before guards pass
- no prompt to mismatched server
- worktree path is printed
- server info is printed
- SSE connects before prompt
- JSONL is valid and flushed
- cleanup is manifest-based
- secrets are redacted
- tests pass

Run:

```bash
uv run pytest
```

Fix failures and report results.
