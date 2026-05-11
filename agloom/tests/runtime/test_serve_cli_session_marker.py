"""Session marker snapshot JSON (no secrets) from serve CLI args."""

from __future__ import annotations

import argparse
import os

from agloom.runtime.serve_cli import session_started_snapshot_from_args


def test_session_started_snapshot_api_key_env_nonempty(monkeypatch) -> None:
    monkeypatch.setenv("MY_SECRET_KEY", "sk-test")
    args = argparse.Namespace(
        model=None,
        provider="openai",
        api_key_env="MY_SECRET_KEY",
        session_max_turns=50,
        auto_summarize=True,
        summarizer_model=None,
        memory_type=None,
        memory_path=None,
        no_memory=False,
    )
    snap = session_started_snapshot_from_args(args)
    assert "sampling" in snap
    assert snap["sampling"]["provider_slug"] == "openai"
    assert snap["effective_config"]["api_key_env"] == "MY_SECRET_KEY"
    assert snap["effective_config"]["api_key_env_nonempty"] is True
    assert snap["effective_config"]["llm_resolution"] == "env_auto"


def test_session_started_snapshot_explicit_model_and_missing_env(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_VAR", raising=False)
    args = argparse.Namespace(
        model="openai:gpt-4o",
        provider=None,
        api_key_env="MISSING_VAR",
        session_max_turns=30,
        auto_summarize=False,
        summarizer_model="anthropic:claude-3-5-haiku",
        memory_type="sqlite",
        memory_path=".agloom/mem.sqlite",
        no_memory=False,
    )
    snap = session_started_snapshot_from_args(args)
    ec = snap["effective_config"]
    assert ec["model"] == "openai:gpt-4o"
    assert ec["llm_resolution"] == "explicit_model"
    assert ec["api_key_env_nonempty"] is False
    assert ec["session_max_turns"] == 30
    assert ec["auto_summarize"] is False
    assert ec["summarizer_model"] == "anthropic:claude-3-5-haiku"
    assert ec["memory_type"] == "sqlite"


def test_session_started_snapshot_env_present_without_api_key_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    args = argparse.Namespace(
        model=None,
        provider=None,
        api_key_env=None,
        session_max_turns=50,
        auto_summarize=True,
        summarizer_model=None,
        memory_type=None,
        memory_path=None,
        no_memory=False,
    )
    snap = session_started_snapshot_from_args(args)
    assert snap["effective_config"]["api_key_env"] is None
    assert snap["effective_config"]["llm_resolution"] == "env_auto"
    del os.environ["OPENAI_API_KEY"]
