from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .errors import ErrorRecord
from .manifest import write_json
from .opencode_client import OpencodeClient
from .records import JsonObject, JsonValue


@dataclass(slots=True)
class CollectionResult:
    session: JsonValue = None
    messages: JsonValue = None
    children: JsonValue = None
    todo: JsonValue = None
    diff: JsonValue = None
    file_status: JsonValue = None
    final_output: str = ""
    errors: list[ErrorRecord] = field(default_factory=list)


def collect_candidate(
    client: OpencodeClient,
    cwd: Path,
    session_id: str,
    result_dir: Path,
) -> CollectionResult:
    errors: list[ErrorRecord] = []

    session = _safe_call(errors, "session", lambda: client.session_get(cwd, session_id))
    messages = _safe_call(errors, "messages", lambda: client.session_messages(cwd, session_id))
    children = _safe_call(errors, "children", lambda: collect_children_recursive(client, cwd, session_id))
    todo = _safe_call(errors, "todo", lambda: client.session_todo(cwd, session_id))
    diff = _safe_call(errors, "diff", lambda: client.session_diff(cwd, session_id))
    file_status = _safe_call(errors, "file_status", lambda: client.file_status(cwd))

    final_output = extract_final_output(messages)
    write_json(result_dir / "session.json", session if session is not None else {})
    write_json(result_dir / "messages.json", messages if messages is not None else [])
    write_json(result_dir / "children.json", children if children is not None else [])
    write_json(result_dir / "todo.json", todo if todo is not None else [])
    write_json(result_dir / "diff.json", diff if diff is not None else {})
    write_json(result_dir / "file-status.json", file_status if file_status is not None else [])
    (result_dir / "final-output.md").write_text(final_output, encoding="utf-8")

    return CollectionResult(
        session=session,
        messages=messages,
        children=children,
        todo=todo,
        diff=diff,
        file_status=file_status,
        final_output=final_output,
        errors=errors,
    )


def collect_children_recursive(
    client: OpencodeClient,
    cwd: Path,
    session_id: str,
    *,
    seen: set[str] | None = None,
    max_depth: int = 20,
) -> list[JsonObject]:
    if max_depth <= 0:
        return []
    visited = seen if seen is not None else {session_id}
    children = client.session_children(cwd, session_id)
    records: list[JsonObject] = []
    for child_id in _extract_child_ids(children):
        if child_id in visited:
            continue
        visited.add(child_id)
        record: JsonObject = {"id": child_id}
        record["session"] = client.session_get(cwd, child_id)
        record["messages"] = client.session_messages(cwd, child_id)
        record["diff"] = client.session_diff(cwd, child_id)
        record["children"] = collect_children_recursive(
            client,
            cwd,
            child_id,
            seen=visited,
            max_depth=max_depth - 1,
        )
        records.append(record)
    return records


def extract_final_output(messages: Any) -> str:
    normalized = _messages_list(messages)
    for message in reversed(normalized):
        role = str(message.get("role") or message.get("type") or "").lower()
        if role and role != "assistant":
            continue
        text = _extract_text(message)
        if text.strip():
            return text.strip() + "\n"
    return ""


def _safe_call(errors: list[ErrorRecord], label: str, func: Callable[[], JsonValue]) -> JsonValue:
    try:
        return func()
    except Exception as exc:  # collection is intentionally best-effort
        errors.append(
            ErrorRecord(
                "collection_failed",
                f"failed to collect {label}: {exc}",
                recoverable=True,
                details={"artifact": label},
            )
        )
        return None


def _extract_child_ids(children: Any) -> list[str]:
    items = _messages_list(children)
    ids: list[str] = []
    for item in items:
        child_id = item.get("id") or item.get("sessionID") or item.get("session_id")
        if isinstance(child_id, str):
            ids.append(child_id)
    return ids


def _messages_list(value: Any) -> list[JsonObject]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("messages", "data", "items", "children"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        return [value]
    return []


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_extract_text(item) for item in value)
    if not isinstance(value, dict):
        return ""
    chunks: list[str] = []
    for key in ("text", "content", "message"):
        item = value.get(key)
        if isinstance(item, str):
            chunks.append(item)
    parts = value.get("parts")
    if isinstance(parts, list):
        chunks.extend(_extract_text(part) for part in parts)
    return "".join(chunks)
