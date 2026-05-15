from __future__ import annotations

import io

from rich.console import Console

from eval_feia.summary import print_summary


def test_print_summary_renders_candidate_values_as_plain_text() -> None:
    output = io.StringIO()
    console = Console(file=output, force_terminal=False, width=240)
    summary = {
        "run_id": "run-1",
        "server": {"url": "http://127.0.0.1:4096"},
        "opencode_version": "fake",
        "repo": {"base_ref": "HEAD", "base_sha": "abc123"},
        "output_dir": "/tmp/out",
        "candidates": [
            {
                "candidate_id": "cand-001",
                "label": "[red]not markup[/red]",
                "branch_name": "eval/run-1/[blue]branch[/blue]",
                "status": "passed",
                "validation_status": "passed",
                "summary": {"files_changed": 1, "additions": 2, "deletions": 3},
                "session_id": "ses_1",
                "worktree_path": "/tmp/[green]worktree[/green]",
            }
        ],
    }

    print_summary(console, summary)

    text = output.getvalue()
    assert "[red]not markup[/red]" in text
    assert "eval/run-1/[blue]branch[/blue]" in text
    assert "/tmp/[green]worktree[/green]" in text
