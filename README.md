# eval-feia Zero-start Documentation Pack

이 문서팩은 `eval-feia`를 0부터 다시 구현하기 위한 Markdown 문서 세트다.

이번 구조에서는 요구사항 문서를 루트에 흩뿌리지 않고 `docs/` 하위 디렉토리에 묶었다. 루트에는 repository entrypoint 성격의 `README.md`와 agent 지시용 `AGENTS.md`만 둔다.

## 읽는 순서

1. `AGENTS.md`
2. `docs/00_INDEX.md`
3. `docs/PRD.md`
4. `docs/REQUIREMENTS.md`
5. `docs/ARCHITECTURE.md`
6. `docs/api/OPENCODE_HTTP_API.md`
7. `docs/OPENCODE_INTEGRATION.md`
8. `docs/RUNTIME_READINESS_SPEC.md`
9. `docs/SERVER_INFO_RESTART_SPEC.md`
10. `docs/LIVE_EXECUTION_UX_SPEC.md`
11. `docs/TEST_PLAN.md`

## 핵심 반영 사항

- OpenCode agent trajectory를 정량화한다.
- OpenCode는 version-pinned `bunx` command로 실행한다.
- run마다 tmp directory 아래 독립 Git worktree를 만든다.
- worktree 생성 직후 화면에 path를 출력한다.
- `opencode serve` 이후 실제 serve된 정보를 출력한다.
- health/cwd/version 검증 전에는 prompt를 보내지 않는다.
- cwd/version mismatch 시 server process group을 종료하고 restart한다.
- prompt 실행 중 Rich Live 또는 JSONL로 실시간 trajectory를 출력한다.
- `docs/api/`에 `opencode serve`에서 사용하는 HTTP API 정보를 포함한다.

## 원본 개요

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
