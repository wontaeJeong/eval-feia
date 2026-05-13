# API Client Contract

## OpenCodeClient responsibilities

The OpenCode client must provide a stable internal contract so runner logic does not depend on raw HTTP details.

## Suggested interface

```python
class OpenCodeClient:
    def get_health(self) -> HealthResponse: ...
    def get_path(self) -> dict: ...
    def get_project_current(self) -> dict: ...
    def create_session(self, title: str, parent_id: str | None = None) -> Session: ...
    def send_prompt_async(self, session_id: str, payload: dict) -> None: ...
    def send_message(self, session_id: str, payload: dict) -> dict: ...
    def get_session_status(self) -> dict: ...
    def get_session_children(self, session_id: str) -> list[dict]: ...
    def get_session_todo(self, session_id: str) -> list[dict]: ...
    def list_messages(self, session_id: str) -> list[dict]: ...
    def get_diff(self, session_id: str) -> list[dict]: ...
    def open_event_stream(self, endpoint: str): ...
```

## Required behavior

- Apply auth consistently.
- Use run-specific base URL.
- Set explicit timeout for non-stream requests.
- Keep streaming request separate from polling request timeout.
- Redact auth and secrets from logs.
- Return typed results or typed exceptions.

## CWD extraction helper

Implement a helper that searches path-like values from raw response.

Candidate keys:

```text
cwd
path
root
directory
project.path
project.root
project.directory
```

Do not mark cwd check successful unless actual path resolves exactly to expected cwd.
