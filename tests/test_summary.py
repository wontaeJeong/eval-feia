from __future__ import annotations

import io

from rich.console import Console

from eval_feia.summary import print_summary


def test_print_summary_renders_candidate_values_as_plain_text() -> None:
    output = io.StringIO()
    console = Console(file=output, force_terminal=False, width=240)
    summary = {
        "run_id": "run-1",
        "label": "[red]not markup[/red]",
        "server": {"url": "http://127.0.0.1:4096"},
        "opencode_version": "fake",
        "repo": {"base_ref": "HEAD", "base_sha": "abc123"},
        "output_dir": "/tmp/out",
        "candidates": [
            {
                "candidate_id": "cand-001",
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
    assert "eval-feia run summary" in text
    assert "CANDIDATE  BRANCH" in text
    assert "eval/run-1/[blue]branch[/blue]" in text
    assert "/tmp/[green]worktree[/green]" in text
    assert "┏" not in text
    assert "└" not in text
    assert "Run ID:" not in text
    assert "Label:" not in text
    assert "Server:" not in text
    assert "Opencode version:" not in text
    assert "Base ref:" not in text
    assert "Output:" not in text
