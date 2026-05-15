# Runtime Flow

## Preflight

1. Load config.
2. Resolve repo path, prompt path, output root, worktree root.
3. Check git repository.
4. Check base ref.
5. Read prompt file.
6. Health check opencode server with retries:

```http
GET /global/health
```

7. Print health result:

```text
opencode server: http://127.0.0.1:4096
opencode version: <version>
```

## Worktree setup

For `N` candidates or top-level `evals` entries:

```bash
git worktree add -b <resolved-branch-name> <worktree-path> <base-ref>
```

Each eval can request a `branch_name` and `label`. `label` is display-only. `branch_name`
is sanitized, validated with `git check-ref-format --branch`, and resolved to a unique branch
if the requested branch or worktree path already exists.

Print each resolved value immediately:

```text
[1/3] candidate: command-body-test
[1/3] eval: command-body-test
[1/3] label: command body test
[1/3] requested branch: eval/command-body-test
[1/3] resolved branch: eval/command-body-test-2
[1/3] worktree: /abs/path/.eval-feia/worktrees/<run-id>/eval-command-body-test-2
```

Record each worktree and its actual branch name in `manifest.json` as soon as it is created.

## Candidate execution

For each candidate:

1. Verify effective path:

```http
GET /path?directory=<encoded-worktree>
```

2. Create session:

```http
POST /session
x-opencode-directory: <encoded-worktree>
```

3. Validate session directory if returned.

4. Send prompt synchronously:

```http
POST /session/{id}/message
x-opencode-directory: <encoded-worktree>
```

5. If request exceeds timeout, abort:

```http
POST /session/{id}/abort
x-opencode-directory: <encoded-worktree>
```

6. Collect artifacts.

7. Run local validation commands in the worktree.

8. Write candidate summary.

## Collection

After each candidate completes or fails, collect as much information as possible:

```http
GET /session/{id}
GET /session/{id}/message
GET /session/{id}/children
GET /session/{id}/todo
GET /session/{id}/diff
GET /file/status
```

Also collect local data:

```bash
git -C <worktree> status --short
git -C <worktree> diff --stat
git -C <worktree> diff --binary
```

## Child sessions

The task/subagent tool can create child sessions. Collect recursively:

```text
root session
  -> children
      -> grandchildren
```

For each child session, collect session info, messages, children, and diff.

MVP does not need to drive child sessions directly. It only needs to detect and collect them.

## Final summary

At the end of `run`, always print and write:

```text
Run ID: <run-id>
Server: <server-url>
Opencode version: <version>
Base ref: <sha/ref>
Output: <result-dir>

Candidate | Label             | Branch         | Status | Validation | Files | Additions | Deletions | Session | Worktree
cand-001  | command body test | eval/foo-2     | passed | passed     | 5     | 120       | 13        | ses_... | /abs/...
cand-002  | attach healthcheck | eval/bar       | failed | failed     | 2     | 44        | 7         | ses_... | /abs/...
```

Also write `run-summary.md` and `run-summary.json`. JSON candidate records include
`eval_id`, `label`, `requested_branch_name`, `branch_name`, `worktree_path`, `session_id`,
and `status`; `branch_name` is the branch actually created or used after suffix resolution.
