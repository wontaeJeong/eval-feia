from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .manifest import Manifest, write_json


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


def write_run_summary(
    manifest: Manifest,
    candidate_results: list[dict[str, Any]],
    *,
    health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir = manifest.output_dir
    passed = all(result.get("status") == "passed" for result in candidate_results)
    summary = {
        "run_id": manifest.run_id,
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


def render_markdown_summary(summary: dict[str, Any]) -> str:
    lines = [
        f"# eval-feia Run {summary['run_id']}",
        "",
        f"Server: {summary['server']['url']}",
        f"Opencode version: {summary.get('opencode_version') or 'unknown'}",
        f"Base ref: {summary['repo']['base_ref']} ({summary['repo']['base_sha']})",
        f"Output: {summary['output_dir']}",
        "",
        "| Candidate | Label | Branch | Status | Validation | Files | Additions | "
        "Deletions | Session | Worktree |",
        "|---|---|---|---|---|---:|---:|---:|---|---|",
    ]
    for candidate in summary["candidates"]:
        stats = candidate.get("summary", {})
        validation = candidate.get("validation_status", "unknown")
        lines.append(
            (
                "| {candidate_id} | {label} | {branch} | {status} | {validation} | "
                "{files} | {adds} | {dels} | {session} | {worktree} |"
            ).format(
                candidate_id=candidate.get("candidate_id", ""),
                label=candidate.get("label", ""),
                branch=candidate.get("branch_name", ""),
                status=candidate.get("status", ""),
                validation=validation,
                files=stats.get("files_changed", 0),
                adds=stats.get("additions", 0),
                dels=stats.get("deletions", 0),
                session=candidate.get("session_id") or "",
                worktree=candidate.get("worktree_path") or "",
            )
        )
    lines.append("")
    return "\n".join(lines)


def print_summary(console: Console, summary: dict[str, Any]) -> None:
    console.print(f"Run ID: {summary['run_id']}", markup=False)
    console.print(f"Server: {summary['server']['url']}", markup=False)
    console.print(
        f"Opencode version: {summary.get('opencode_version') or 'unknown'}",
        markup=False,
    )
    console.print(
        f"Base ref: {summary['repo']['base_ref']} ({summary['repo']['base_sha']})",
        markup=False,
    )
    console.print(f"Output: {summary['output_dir']}", markup=False)

    table = Table(title="eval-feia results")
    for column in (
        "Candidate",
        "Label",
        "Branch",
        "Status",
        "Validation",
        "Files",
        "Additions",
        "Deletions",
        "Session",
        "Worktree",
    ):
        table.add_column(column)
    for candidate in summary["candidates"]:
        stats = candidate.get("summary", {})
        table.add_row(
            _plain_text(candidate.get("candidate_id", "")),
            _plain_text(candidate.get("label", "")),
            _plain_text(candidate.get("branch_name", "")),
            _plain_text(candidate.get("status", "")),
            _plain_text(candidate.get("validation_status", "unknown")),
            _plain_text(stats.get("files_changed", 0)),
            _plain_text(stats.get("additions", 0)),
            _plain_text(stats.get("deletions", 0)),
            _plain_text(candidate.get("session_id") or ""),
            _plain_text(candidate.get("worktree_path") or ""),
        )
    console.print(table)


def _plain_text(value: object) -> Text:
    return Text(str(value))
