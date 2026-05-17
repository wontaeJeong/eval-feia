from __future__ import annotations

from typing import Any

from rich.console import Console

from .manifest import Manifest, write_json
from .plain_table import print_plain_table


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


def render_markdown_summary(summary: dict[str, Any]) -> str:
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
            "| Candidate | Branch | Status | Validation | Files | Additions | "
            "Deletions | Session | Worktree |",
            "|---|---|---|---|---:|---:|---:|---|---|",
        ]
    )
    for candidate in summary["candidates"]:
        stats = candidate.get("summary", {})
        validation = candidate.get("validation_status", "unknown")
        lines.append(
            (
                "| {candidate_id} | {branch} | {status} | {validation} | "
                "{files} | {adds} | {dels} | {session} | {worktree} |"
            ).format(
                candidate_id=candidate.get("candidate_id", ""),
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
    console.print("eval-feia run summary", markup=False)
    rows = []
    for candidate in summary["candidates"]:
        stats = candidate.get("summary", {})
        rows.append(
            (
                str(candidate.get("candidate_id", "")),
                str(candidate.get("branch_name", "")),
                str(candidate.get("status", "")),
                str(candidate.get("validation_status", "unknown")),
                str(stats.get("files_changed", 0)),
                str(stats.get("additions", 0)),
                str(stats.get("deletions", 0)),
                str(candidate.get("session_id") or ""),
                str(candidate.get("worktree_path") or ""),
            )
        )
    print_plain_table(
        console,
        (
            "CANDIDATE",
            "BRANCH",
            "STATUS",
            "VALIDATION",
            "FILES",
            "ADDITIONS",
            "DELETIONS",
            "SESSION",
            "WORKTREE",
        ),
        rows,
    )
