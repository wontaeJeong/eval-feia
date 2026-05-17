from __future__ import annotations

from pathlib import Path
from typing import Any

from eval_feia.collector import collect_children_recursive


class CyclicChildClient:
    def session_children(self, cwd: Path, session_id: str) -> list[dict[str, str]]:
        children = {
            "root": [{"id": "child"}],
            "child": [{"id": "root"}],
        }
        return children.get(session_id, [])

    def session_get(self, cwd: Path, session_id: str) -> dict[str, str]:
        return {"id": session_id}

    def session_messages(self, cwd: Path, session_id: str) -> list[Any]:
        return []

    def session_diff(self, cwd: Path, session_id: str) -> dict[str, list[Any]]:
        return {"files": []}


def test_collect_children_recursive_skips_cycles(tmp_path: Path) -> None:
    records = collect_children_recursive(CyclicChildClient(), tmp_path, "root")

    assert records == [
        {
            "id": "child",
            "session": {"id": "child"},
            "messages": [],
            "diff": {"files": []},
            "children": [],
        }
    ]
