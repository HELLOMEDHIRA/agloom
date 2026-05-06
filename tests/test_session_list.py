"""Tests for session discovery (agloom sessions)."""

from __future__ import annotations

import json
from pathlib import Path

from agloom_cli.session_list import (
    get_config_current_session_id,
    list_session_rows,
    load_session_row,
)


def test_load_session_row_minimal(tmp_path: Path) -> None:
    p = tmp_path / "abc123.json"
    p.write_text(
        json.dumps(
            {
                "id": "abc123",
                "started_at": "2026-01-01T00:00:00+00:00",
                "last_active": "2026-01-02T00:00:00+00:00",
                "turns": 2,
                "messages": [{"role": "user", "content": "hello world"}],
                "last_run": {"project_root": "/proj", "resolved": {"model": "groq:llama"}},
            }
        ),
        encoding="utf-8",
    )
    row = load_session_row(p)
    assert row is not None
    assert row["id"] == "abc123"
    assert row["turns"] == 2
    assert "hello" in row["preview"]
    assert row["project_root"] == "/proj"
    assert row["model"] == "groq:llama"


def test_load_session_row_ai_overlay_model(tmp_path: Path) -> None:
    base = tmp_path / "sess1.json"
    base.write_text(
        json.dumps(
            {
                "id": "sess1",
                "messages": [],
                "ai": {"model": "litellm:groq/llama-3.3-70b-versatile"},
            }
        ),
        encoding="utf-8",
    )
    row = load_session_row(base)
    assert row is not None
    assert row["model"] == "litellm:groq/llama-3.3-70b-versatile"


def test_load_session_row_model_binding_fallback(tmp_path: Path) -> None:
    """When ``last_run.resolved.model`` is missing, use ``model_binding.effective_model``."""
    p = tmp_path / "sess.json"
    p.write_text(
        json.dumps(
            {
                "id": "sess",
                "messages": [],
                "model_binding": {"effective_model": "ollama:llama3.2"},
            }
        ),
        encoding="utf-8",
    )
    row = load_session_row(p)
    assert row is not None
    assert row["model"] == "ollama:llama3.2"


def test_list_session_rows_order(tmp_path: Path) -> None:
    d = tmp_path / "sessions"
    d.mkdir()
    older = d / "older.json"
    newer = d / "newer.json"
    older.write_text(
        json.dumps({"id": "older", "last_active": "2026-01-01T00:00:00+00:00", "messages": []}),
        encoding="utf-8",
    )
    newer.write_text(
        json.dumps({"id": "newer", "last_active": "2026-01-03T00:00:00+00:00", "messages": []}),
        encoding="utf-8",
    )
    rows = list_session_rows(d)
    assert [r["id"] for r in rows] == ["newer", "older"]


def test_get_config_current_session_id() -> None:
    assert get_config_current_session_id({}) is None
    assert get_config_current_session_id({"session": {"current_session": "deadbeef" * 4}}) == "deadbeef" * 4
