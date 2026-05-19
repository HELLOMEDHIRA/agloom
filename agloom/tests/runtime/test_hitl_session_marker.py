"""HITL allowlist persistence into session marker JSON (stdio transport layout)."""

from __future__ import annotations

import json
from pathlib import Path

from agloom.runtime.hitl_allowlist import (
    hitl_allowlist_paths_for_runtime,
    load_allowlist_from_session_marker,
    save_allowlist_to_session_marker,
)


def test_save_allowlist_merges_session_marker(tmp_path: Path) -> None:
    marker = tmp_path / "sess_a.json"
    marker.write_text(
        json.dumps(
            {"session_id": "sess_a", "started_at": "2020-01-01T00:00:00Z", "transport": "stdio"},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    save_allowlist_to_session_marker(marker, {"bash", "execute"})
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data["session_id"] == "sess_a"
    assert set(data["hitl_tool_allowlist"]) == {"bash", "execute"}


def test_hitl_allowlist_paths_session_scoped(tmp_path: Path) -> None:
    from argparse import Namespace

    sd = tmp_path / ".agloom" / "sessions"
    sd.mkdir(parents=True)
    marker = sd / "abc.json"
    marker.write_text(
        json.dumps({"hitl_tool_allowlist": ["read_file"]}, indent=2) + "\n",
        encoding="utf-8",
    )
    args = Namespace(no_hitl_allowlist_persist=False, hitl_allowlist_path=None)
    tools, leg, sess = hitl_allowlist_paths_for_runtime(
        args,
        session_marker_json=marker,
        session_scoped=True,
        cwd=tmp_path,
    )
    assert tools.global_tools() == {"read_file"}
    assert leg is None
    assert sess == marker
