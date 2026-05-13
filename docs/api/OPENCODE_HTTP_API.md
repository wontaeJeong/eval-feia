# OpenCode HTTP API Reference for eval-feia

이 문서는 `eval-feia`가 `opencode serve`와 통신할 때 사용하는 HTTP API 정보를 구현 관점에서 정리한다.

기준일: 2026-05-13.

주의: OpenCode는 빠르게 변경될 수 있다. 구현은 공식 문서와 실행 중인 서버의 `/doc` OpenAPI 3.1 문서를 모두 확인할 수 있게 작성한다.

## Server execution

OpenCode server는 headless HTTP server로 동작한다.

```bash
opencode serve [--port <number>] [--hostname <string>] [--cors <origin>]
```

`eval-feia`에서는 전역 설치된 `opencode`를 직접 호출하지 않는다. 반드시 version-pinned `bunx` command builder를 사용한다.

```bash
bunx -p opencode-ai@<version> opencode serve --hostname 127.0.0.1 --port <port>
```

## Authentication

`OPENCODE_SERVER_PASSWORD`를 설정하면 HTTP basic auth가 적용된다. 기본 username은 `opencode`다.

모든 HTTP request는 동일한 auth 설정을 사용해야 한다.

- health
- cwd check
- project/path check
- session create
- prompt send
- SSE stream
- status/children/todo polling

password, auth header, token은 log/result에 저장하지 않는다.

## OpenAPI document

실행 중인 server는 다음 endpoint로 OpenAPI 3.1 spec을 제공한다.

```text
GET /doc
```

예시:

```text
http://127.0.0.1:4096/doc
```

## API endpoint summary

| Group | Method | Path | Purpose |
|---|---:|---|---|
| Global | GET | `/global/health` | health/version 확인 |
| Global | GET | `/global/event` | global SSE stream |
| Events | GET | `/event` | server SSE stream |
| Project | GET | `/project/current` | 현재 project 확인 |
| Path | GET | `/path` | 현재 path/cwd 확인 |
| VCS | GET | `/vcs` | VCS 정보 확인 |
| Session | POST | `/session` | session 생성 |
| Session | GET | `/session/status` | 전체 session status |
| Session | GET | `/session/:id` | session 상세 |
| Session | GET | `/session/:id/children` | child session 조회 |
| Session | GET | `/session/:id/todo` | todo 조회 |
| Session | GET | `/session/:id/diff` | session diff 조회 |
| Message | GET | `/session/:id/message` | message 목록 |
| Message | POST | `/session/:id/message` | message 전송 후 응답 대기 |
| Message | POST | `/session/:id/prompt_async` | 비동기 prompt 전송 |
| File | GET | `/file/status` | tracked file status |
| File | GET | `/file/content?path=<p>` | file content 조회 |
| Docs | GET | `/doc` | OpenAPI spec page |

## Required request flow

`eval-feia run`의 OpenCode HTTP flow는 다음 순서를 따른다.

```text
1. start opencode serve subprocess
2. GET /global/health
3. GET /path
4. fallback GET /project/current
5. emit worktree path and server_info
6. POST /session
7. connect SSE stream: /event or /global/event
8. POST /session/:id/prompt_async
9. poll /session/status
10. poll /session/:id/children
11. poll /session/:id/todo
12. collect /session/:id/message
13. collect /session/:id/diff
```

## GET /global/health

Purpose:

- server가 살아 있는지 확인
- 실제 reported version 확인

Expected response:

```json
{
  "healthy": true,
  "version": "1.4.6"
}
```

Readiness success:

```text
HTTP 200
healthy == true
version exists
```

## GET /path

Purpose:

- server가 실제 어떤 cwd/path 기준으로 떠 있는지 확인

Response schema는 OpenCode version에 따라 달라질 수 있으므로 아래 key를 robust하게 탐색한다.

```text
cwd
path
root
directory
```

## GET /project/current

Purpose:

- `/path`만으로 actual cwd를 확정할 수 없을 때 fallback

Nested key 후보:

```text
project.path
project.root
project.directory
```

## POST /session

Purpose:

- run별 parent session 생성

Request body example:

```json
{
  "parentID": null,
  "title": "eval-feia run-001"
}
```

## POST /session/:id/prompt_async

Purpose:

- prompt를 비동기 전송한다.
- live UX/SSE reader를 block하지 않는 기본 경로다.

Response:

```text
204 No Content
```

Body는 `/session/:id/message`와 동일한 형식을 사용한다.

Example body:

```json
{
  "messageID": null,
  "model": {
    "providerID": "openai",
    "modelID": "gpt-5.5"
  },
  "agent": "impl",
  "noReply": false,
  "system": null,
  "tools": null,
  "parts": [
    {
      "type": "text",
      "text": "웹 검색 후 Knox 메일 리포트 에이전트 작성"
    }
  ]
}
```

## POST /session/:id/message

Purpose:

- message를 보내고 response를 기다린다.

주의:

- blocking endpoint로 동작할 수 있다.
- 사용 시 반드시 별도 thread/task에서 실행해 live renderer와 SSE reader를 block하지 않는다.

## SSE endpoints

Candidate endpoints:

```text
GET /event
GET /global/event
```

Implementation policy:

- 설정값 또는 feature detection으로 사용할 endpoint를 결정한다.
- 실제 사용한 endpoint는 `run.json.live_summary.sse_endpoint`에 저장한다.
- prompt 전송 전에 SSE listener가 read loop에 진입해야 한다.

SSE parser는 다음 형식을 처리한다.

```text
event: server.connected
data: {"type":"server.connected"}

```

Multi-line data도 처리한다.

## Session polling endpoints

### GET /session/status

Purpose:

- parent 및 descendant session idle/busy 확인

### GET /session/:id/children

Purpose:

- subagent session 추적
- immediate child뿐 아니라 descendant 전체를 확인한다.

### GET /session/:id/todo

Purpose:

- todo 상태를 live UX와 completion detector에 반영한다.

## CWD verification policy

Expected cwd:

```text
subprocess cwd.resolve()
```

Actual cwd:

```text
/path or /project/current에서 추출한 path.resolve()
```

Policy:

```text
match    -> continue
mismatch -> kill/restart
unknown  -> fail or restart according to config
skipped  -> only when --no-cwd-check
```

## Version verification policy

Requested version:

```text
--opencode-version
```

Reported version:

```text
/global/health.version
```

Policy:

```text
match    -> continue
mismatch -> kill/restart
unknown  -> record warning; configurable fatal mode can be added later
```

## Error handling

Every request must have timeout.

Recommended exception classification:

```text
OpenCodeConnectionError
OpenCodeTimeoutError
OpenCodeAuthError
OpenCodeUnexpectedResponse
OpenCodeSSEError
```
