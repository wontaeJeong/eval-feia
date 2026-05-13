# Prompt 04: Runtime Readiness and Restart

Implement runtime guards.

Requirements:

- poll `/global/health`
- compare requested/reported version
- verify cwd using `/path` and `/project/current`
- emit served server info
- print server info in CLI
- restart on version/cwd mismatch
- never send prompt to mismatched server
- record restart history

Add fake server tests for version mismatch and cwd mismatch.
