# Prompt 02: Implement Worktree and Manifest

Implement the worktree manager and manifest writer.

Requirements:

- create detached Git worktree per run
- use temp root
- resolve absolute path
- print path immediately
- emit JSONL `worktree_created` event in JSON mode
- write path to `run.json` and `manifest.json`
- cleanup only manifest-owned paths

Add tests for path output, distinct paths, and cleanup safety.
