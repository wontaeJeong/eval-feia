# eval-feia Zero-Base Design Pack

Date: 2026-05-14

This pack defines the MVP for `eval-feia`: a REST-only evaluator for opencode worktree experiments.

The key decision is simple:

- `eval-feia` does not start or own `opencode serve`.
- The user starts `opencode serve` separately.
- `eval-feia run` creates worktrees, then calls the already-running opencode HTTP server with each worktree as the effective directory context.
- `eval-feia run` waits for execution, collects messages, diffs, status, artifacts, and local validation output, then prints and writes the final result summary automatically.
- `eval-feia clean` removes only files and git worktrees recorded in the manifest.

The MVP command surface is intentionally small:

```bash
eval-feia run --config eval-feia.yaml

eval-feia clean --manifest .eval-feia/runs/<run-id>/manifest.json
```

The detailed REST reference is in `docs/opencode-rest-api.md`. The implementation plan is in `docs/implementation-plan.md`. The CLI contract is in `docs/cli.md`.

## Source basis

This design is based on the opencode server and SDK documentation and the generated SDK/client source available from the opencode project.

Primary source URLs:

- https://opencode.ai/docs/server/
- https://opencode.ai/docs/sdk/
- https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/sdk/js/src/client.ts
- https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/sdk/js/src/gen/sdk.gen.ts

Because opencode publishes a live OpenAPI 3.1 spec from the running server, the implementation must also support `GET http://<host>:<port>/doc` as the local runtime source of truth for the installed opencode version.
