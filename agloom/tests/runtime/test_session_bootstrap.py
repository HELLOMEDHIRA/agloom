"""Shared runtime session bootstrap helpers."""

from __future__ import annotations

import argparse
from argparse import Namespace
from pathlib import Path

import pytest

from agloom.runtime.session_bootstrap import prepare_runtime_session


def _args(**kw: object) -> Namespace:
    base = argparse.Namespace(
        memory_type="in-memory",
        session_max_turns=10,
        auto_summarize=False,
    )
    for k, v in kw.items():
        setattr(base, k, v)
    return base


def test_prepare_runtime_session_stdio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    prepared = prepare_runtime_session(
        _args(),
        transport="stdio",
        session_id="sess_test",
        initial_thread="thread_main",
    )
    assert prepared.session_id == "sess_test"
    assert prepared.initial_thread == "thread_main"
    assert prepared.marker_path is not None
    assert prepared.marker_path.is_file()


def test_prepare_runtime_session_ws_query_overrides_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    prepared = prepare_runtime_session(
        _args(model="openai:gpt-4o-mini"),
        transport="ws",
        ws_path_query="/?model=anthropic:claude-3-5-sonnet-20241022",
    )
    assert prepared.session_id.startswith("sess_")
    merged_model = getattr(prepared.working_args, "model", None)
    assert merged_model is not None
    assert "anthropic" in str(merged_model).lower() or "claude" in str(merged_model).lower()
