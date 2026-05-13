# pyright: reportMissingImports=false
from __future__ import annotations

import json
from pathlib import Path

from eval_feia.cleanup import cleanup_manifest
from eval_feia.worktree import create_worktree, resolve_base_commit


def test_worktree_path_is_printed_and_cleanup_is_manifest_based(git_repo: Path, tmp_path: Path) -> None:
    emitted: list[Path] = []
    base_commit = resolve_base_commit(git_repo, "HEAD")
    info = create_worktree(git_repo, tmp_path / "run-001", "HEAD", base_commit, emitted.append)
    assert Path(info.path).is_absolute()
    assert emitted == [Path(info.path)]
    temp_path = tmp_path / "owned-temp"
    temp_path.mkdir()
    untouched = tmp_path / "not-owned"
    untouched.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "repo": str(git_repo),
                "runs": [{"run_id": "run-001", "worktree": {"path": info.path}, "temp_paths": [str(temp_path)]}],
            }
        ),
        encoding="utf-8",
    )
    actions = cleanup_manifest(manifest)
    assert any(action["kind"] == "worktree" for action in actions)
    assert not Path(info.path).exists()
    assert not temp_path.exists()
    assert untouched.exists()
