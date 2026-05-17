# Runtime Flow

## Preflight

1. Build runtime config from CLI arguments.
2. Resolve repo path, prompt path, generated artifact output root, worktree root, stored result root, and SQLite DB path.
3. Check git repository.
4. Check base ref.
5. Read prompt file.
6. Health check opencode server with retries. The default preflight budget is 10 attempts, 500ms between attempts, and a 2s timeout per health request:

```http
GET /global/health
```

`run` first creates a durable stored result directory, starts a stored result record, and prints it:

```text
Run ID: <run-id>
Output directory: /home/user/.eval-feia/results/runs/<run-id>
```

7. Print health and run context:

```text
opencode server: http://127.0.0.1:4096
opencode version: <version>
run id: <run-id>
repository: <repo-root>
base ref: <base-ref> (<base-sha>)
output dir: <output-dir>
worktree root: <worktree-root>
candidates: <count>; concurrency: <count>
opencode request: message | command /<name>
validation commands: <count>
```

## Worktree setup

For `N` candidates or programmatic eval entries:

```bash
git worktree add -b <resolved-branch-name> <worktree-path> <base-ref>
```

Each candidate gets a generated branch name under `eval/<run-id>/...`. The name is
sanitized, validated with `git check-ref-format --branch`, and resolved to a unique branch if
the requested branch or worktree path already exists. Worktree directory paths stay compact:
the run ID is the parent directory and the candidate ID is the leaf directory.

Print created worktrees as a compact CLI table:

```text
#  WORKTREE
1  /abs/path/.eval-feia/worktrees/<run-id>/command-body-test
```

Record each worktree and its actual branch name in `manifest.json` as soon as it is created. Generated artifact and worktree roots include eval-feia marker files that `clean` validates before deleting root directories. When the SQLite DB path is the default database under the generated artifact root, record that DB path in the manifest for `clean --delete-index`.

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

4. Send prompt synchronously. Without `run.command`, use:

```http
POST /session/{id}/message
x-opencode-directory: <encoded-worktree>
```

With `run.command`, use the slash-command endpoint instead and send the prompt text as string `arguments`:

```http
POST /session/{id}/command
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

At the end of `run`, print the result table, write generated summary files, update the SQLite index, and complete the durable stored result record. Do not repeat the
run metadata already printed before candidate execution.

```text
progress: writing final summary
eval-feia run summary
CANDIDATE  BRANCH             STATUS  VALIDATION  FILES  ADDITIONS  DELETIONS  SESSION  WORKTREE
cand-001   eval/<run-id>/foo  passed  passed      5      120        13         ses_...  /abs/...
cand-002   eval/<run-id>/bar  failed  failed      2      44         7          ses_...  /abs/...
```

Also write `run-summary.md` and `run-summary.json` under the generated artifact output root, and copy text summaries into the durable stored result root. JSON candidate records include
`eval_id` only when it differs from the candidate ID, plus `base_ref`, `base_sha`,
`requested_branch_name`, `branch_name`, `worktree_path`, `session_id`, and `status`;
`branch_name` is the branch actually created or used after suffix resolution. The run label is
recorded once at run-summary level.
