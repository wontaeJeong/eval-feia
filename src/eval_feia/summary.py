from __future__ import annotations

from typing import Any

from rich.console import Console

from .manifest import Manifest, write_json
from .plain_table import print_plain_table
from .records import CandidateResult, JsonObject, RunSummary


def parse_numstat(numstat: str) -> dict[str, int]:
    files = 0
    additions = 0
    deletions = 0
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        files += 1
        if parts[0] != "-":
            additions += int(parts[0])
        if parts[1] != "-":
            deletions += int(parts[1])
    return {"files_changed": files, "additions": additions, "deletions": deletions}


def extract_opencode_metrics(
    session: Any,
    messages: Any,
    children: Any = None,
) -> dict[str, int | float | None]:
    session_metrics = _extract_token_cost_metrics(session)
    message_metrics = _extract_token_cost_metrics(messages)
    children_metrics = _extract_token_cost_metrics(children)
    fallback_metrics = _merge_metrics(
        message_metrics,
        children_metrics,
    )
    token_metrics = _prefer_metrics(session_metrics, fallback_metrics)
    return {
        "token_input": _int_metric(token_metrics.get("token_input")),
        "token_output": _int_metric(token_metrics.get("token_output")),
        "token_reasoning": _int_metric(token_metrics.get("token_reasoning")),
        **_count_tool_calls(messages, children),
        "cost_total": _float_metric(token_metrics.get("cost_total")),
    }


def write_run_summary(
    manifest: Manifest,
    candidate_results: list[CandidateResult],
    *,
    health: JsonObject | None = None,
) -> RunSummary:
    output_dir = manifest.output_dir
    passed = all(result.get("status") == "passed" for result in candidate_results)
    summary: RunSummary = {
        "run_id": manifest.run_id,
        "label": manifest.label,
        "server": manifest.server.model_dump(mode="json"),
        "opencode_version": manifest.server.version,
        "repo": manifest.repo.model_dump(mode="json"),
        "output_dir": str(output_dir),
        "passed": passed,
        "health": health or {},
        "candidates": candidate_results,
    }
    write_json(output_dir / "run-summary.json", summary)
    (output_dir / "run-summary.md").write_text(render_markdown_summary(summary), encoding="utf-8")
    return summary


def render_markdown_summary(summary: RunSummary) -> str:
    lines = [
        f"# eval-feia Run {summary['run_id']}",
        "",
        f"Server: {summary['server']['url']}",
        f"Opencode version: {summary.get('opencode_version') or 'unknown'}",
    ]
    if summary.get("label"):
        lines.append(f"Label: {summary['label']}")
    lines.extend(
        [
            f"Base ref: {summary['repo']['base_ref']} ({summary['repo']['base_sha']})",
            f"Output: {summary['output_dir']}",
            "",
            "| Candidate | Status | Validation | Elapsed | Files | Additions | "
            "Deletions | Tools | Tool OK | Tool Errors | Token In | Token Out | Reason |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for candidate in summary["candidates"]:
        stats = candidate.get("summary", {})
        validation = candidate.get("validation_status", "unknown")
        lines.append(
            (
                "| {candidate_id} | {status} | {validation} | {elapsed} | "
                "{files} | {adds} | {dels} | {tools} | {tool_success} | {tool_errors} | "
                "{token_in} | {token_out} | "
                "{reason} |"
            ).format(
                candidate_id=candidate.get("candidate_id", ""),
                status=_display_status(candidate),
                validation=validation,
                elapsed=_format_elapsed(candidate.get("duration_seconds")),
                files=stats.get("files_changed", 0),
                adds=stats.get("additions", 0),
                dels=stats.get("deletions", 0),
                tools=_metric_text(stats.get("tool_call_count")),
                tool_success=_metric_text(stats.get("tool_success_count")),
                tool_errors=_metric_text(stats.get("tool_error_count")),
                token_in=_metric_text(stats.get("token_input")),
                token_out=_metric_text(stats.get("token_output")),
                reason=_metric_text(stats.get("token_reasoning")),
            )
        )
    lines.append("")
    return "\n".join(lines)


def print_summary(console: Console, summary: RunSummary) -> None:
    console.print("eval-feia run summary", markup=False)
    rows = []
    for candidate in summary["candidates"]:
        stats = candidate.get("summary", {})
        rows.append(
            (
                str(candidate.get("candidate_id", "")),
                _display_status(candidate),
                str(candidate.get("validation_status", "unknown")),
                _format_elapsed(candidate.get("duration_seconds")),
                str(stats.get("files_changed", 0)),
                str(stats.get("additions", 0)),
                str(stats.get("deletions", 0)),
                _metric_text(stats.get("tool_call_count")),
                _metric_text(stats.get("tool_success_count")),
                _metric_text(stats.get("tool_error_count")),
                _metric_text(stats.get("token_input")),
                _metric_text(stats.get("token_output")),
                _metric_text(stats.get("token_reasoning")),
            )
        )
    print_plain_table(
        console,
        (
            "CANDIDATE",
            "STATUS",
            "VALIDATION",
            "ELAPSED",
            "FILES",
            "ADDITIONS",
            "DELETIONS",
            "TOOLS",
            "TOOL_OK",
            "TOOL_ERR",
            "TOKEN_IN",
            "TOKEN_OUT",
            "REASON",
        ),
        rows,
    )


def _extract_token_cost_metrics(value: Any) -> dict[str, int | float | None]:
    metrics: dict[str, int | float | None] = {
        "token_input": None,
        "token_output": None,
        "token_reasoning": None,
        "cost_total": None,
    }
    for item in _walk_json(value):
        if not isinstance(item, dict):
            continue
        _add_explicit_metrics(metrics, item)
        tokens = item.get("tokens") or item.get("usage")
        if isinstance(tokens, dict):
            _add_token_container(metrics, tokens)
    return metrics


def _add_explicit_metrics(metrics: dict[str, int | float | None], item: dict[str, Any]) -> None:
    _add_int_metric(
        metrics,
        "token_input",
        item,
        ("input_tokens", "inputTokens", "prompt_tokens", "promptTokens"),
    )
    _add_int_metric(
        metrics,
        "token_output",
        item,
        ("output_tokens", "outputTokens", "completion_tokens", "completionTokens"),
    )
    _add_int_metric(
        metrics,
        "token_reasoning",
        item,
        ("reasoning_tokens", "reasoningTokens", "reasoningOutputTokens", "reasoning_output_tokens"),
    )
    _add_float_metric(metrics, "cost_total", item, ("cost", "total_cost", "totalCost"))


def _add_token_container(metrics: dict[str, int | float | None], tokens: dict[str, Any]) -> None:
    _add_int_metric(metrics, "token_input", tokens, ("input",))
    _add_int_metric(metrics, "token_output", tokens, ("output",))
    _add_int_metric(metrics, "token_reasoning", tokens, ("reasoning",))


def _add_int_metric(
    metrics: dict[str, int | float | None],
    metric_key: str,
    item: dict[str, Any],
    keys: tuple[str, ...],
) -> None:
    for key in keys:
        value = _int_metric(item.get(key))
        if value is not None:
            current = metrics.get(metric_key)
            metrics[metric_key] = int(current or 0) + value
            return


def _add_float_metric(
    metrics: dict[str, int | float | None],
    metric_key: str,
    item: dict[str, Any],
    keys: tuple[str, ...],
) -> None:
    for key in keys:
        value = _float_metric(item.get(key))
        if value is not None:
            current = metrics.get(metric_key)
            metrics[metric_key] = float(current or 0.0) + value
            return


def _merge_metrics(*items: dict[str, int | float | None]) -> dict[str, int | float | None]:
    merged: dict[str, int | float | None] = {
        "token_input": None,
        "token_output": None,
        "token_reasoning": None,
        "cost_total": None,
    }
    for item in items:
        for key, value in item.items():
            if value is None:
                continue
            if isinstance(value, float):
                merged[key] = float(merged.get(key) or 0.0) + value
            else:
                merged[key] = int(merged.get(key) or 0) + value
    return merged


def _prefer_metrics(
    preferred: dict[str, int | float | None],
    fallback: dict[str, int | float | None],
) -> dict[str, int | float | None]:
    return {key: value if value is not None else fallback.get(key) for key, value in preferred.items()}


def _count_tool_calls(*values: Any) -> dict[str, int | None]:
    statuses: dict[str, str | None] = {}
    anonymous_index = 0
    for item in _walk_json(values):
        if not isinstance(item, dict):
            continue
        if item.get("type") != "tool" and "tool" not in item and "toolID" not in item:
            continue
        call_id = item.get("id") or item.get("callID") or item.get("toolCallID")
        if isinstance(call_id, str) and call_id:
            key = call_id
        else:
            anonymous_index += 1
            key = f"anonymous-{anonymous_index}"
        statuses[key] = _tool_status(item) or statuses.get(key)
    count = len(statuses)
    success = sum(1 for status in statuses.values() if status == "completed")
    errors = sum(1 for status in statuses.values() if status == "error")
    return {
        "tool_call_count": count if count else None,
        "tool_success_count": success if success else None,
        "tool_error_count": errors if errors else None,
    }


def _tool_status(item: dict[str, Any]) -> str | None:
    state = item.get("state")
    if isinstance(state, dict):
        status = state.get("status")
        if isinstance(status, str):
            return status
    if isinstance(state, str):
        return state
    status = item.get("status")
    return status if isinstance(status, str) else None


def _walk_json(value: Any) -> list[Any]:
    items = [value]
    index = 0
    while index < len(items):
        current = items[index]
        index += 1
        if isinstance(current, dict):
            items.extend(current.values())
        elif isinstance(current, list | tuple):
            items.extend(current)
    return items


def _display_status(candidate: dict[str, Any]) -> str:
    error = candidate.get("error")
    if isinstance(error, dict):
        kind = error.get("kind")
        if kind in {"timeout", "aborted"}:
            return str(kind)
    status = str(candidate.get("status") or "")
    if status == "passed":
        return "completed"
    return status or "unknown"


def _format_elapsed(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{seconds:.3f}s"


def _metric_text(value: Any) -> str:
    metric = _int_metric(value)
    return "" if metric is None else str(metric)


def _int_metric(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _float_metric(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
