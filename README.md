# eval-feia Documentation Pack

> Scope: eval-feia zero-start implementation.
> Updated: 2026-05-13.
> Assumption: implementation starts from an empty or near-empty repository.

This documentation pack describes the zero-start implementation plan for `eval-feia`.

`eval-feia` is an OpenCode Agent Evaluation Harness. It runs the same task through OpenCode server instances, captures each agent trajectory, validates the produced AutoGen Teams JSON Component Config, and writes structured metrics for comparison.

The current target task is:

> 웹 검색 후 Knox 메일 리포트 에이전트 작성

The package includes requirements, architecture, OpenCode API notes, runtime readiness checks, live execution UX, data schemas, validation, security, test planning, and implementation tasks.

## Required reading order

1. `PROJECT_CONTEXT.md`
2. `PRD.md`
3. `REQUIREMENTS.md`
4. `ARCHITECTURE.md`
5. `OPENCODE_API_REFERENCE.md`
6. `OPENCODE_INTEGRATION.md`
7. `WORKTREE_SPEC.md`
8. `RUNTIME_READINESS_SPEC.md`
9. `LIVE_EXECUTION_UX_SPEC.md`
10. `SERVER_INFO_RESTART_SPEC.md`
11. `TRAJECTORY_METRICS.md`
12. `DATA_SCHEMA.md`
13. `VALIDATION_SPEC.md`
14. `CLI_SPEC.md`
15. `TEST_PLAN.md`
16. `IMPLEMENTATION_PLAN.md`
17. `TASK_BREAKDOWN.md`
18. `AGENTS.md`

## Separate prompt pack

The actual agent work prompts are packaged separately in `eval-feia-zero-start-prompts.zip`. Use the master prompt first if one agent will implement the project end-to-end. Use the phase prompts if you want to split the work into smaller jobs.
