"""Session marker snapshot JSON and resume env wiring (secrets only when explicitly opted in)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pytest

from agloom.runtime.serve_cli import (
    SESSION_MARKER_DEFAULT_FREQUENCY_PENALTY,
    SESSION_MARKER_DEFAULT_MAX_TOKENS,
    SESSION_MARKER_DEFAULT_PRESENCE_PENALTY,
    inject_api_key_secret_from_session_marker,
    merge_api_key_env_from_session_marker,
    session_started_snapshot_from_args,
)


def test_session_started_snapshot_api_key_env_nonempty(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
    assert snap["effective_config"]["provider_resolved"] == "openai"
    cred = snap["effective_config"]["provider_credential_env"]
    assert cred == [{"env": "OPENAI_API_KEY", "present": False}]
    assert snap["effective_config"]["api_key_env"] == "MY_SECRET_KEY"
    assert snap["effective_config"]["api_key_env_nonempty"] is True
    assert snap["effective_config"]["credential_env_var"] == "MY_SECRET_KEY"
    assert snap["effective_config"]["credential_env_var_nonempty"] is True
    assert snap["effective_config"]["provider_primary_api_key_env"] is None
    assert snap["effective_config"]["llm_resolution"] == "env_auto"
    ec = snap["effective_config"]
    assert ec["provider_primary_credential_present"] is False
    assert ec["max_tokens"] == SESSION_MARKER_DEFAULT_MAX_TOKENS
    assert ec["frequency_penalty"] == SESSION_MARKER_DEFAULT_FREQUENCY_PENALTY
    assert ec["presence_penalty"] == SESSION_MARKER_DEFAULT_PRESENCE_PENALTY
    assert "api_key_secret" not in ec


def test_session_started_snapshot_persist_api_key_writes_secret(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("MY_SECRET_KEY", "sk-persist-test")
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
        persist_api_key_in_session_marker=True,
    )
    snap = session_started_snapshot_from_args(args)
    ec = snap["effective_config"]
    assert ec["api_key_secret"] == "sk-persist-test"
    assert ec["persist_api_key_in_session_marker"] is True


def test_session_started_snapshot_env_var_enables_persist(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AGLOOM_PERSIST_API_KEY_IN_SESSION_MARKER", "1")
    monkeypatch.setenv("MY_K", "secret-from-env-flag")
    args = argparse.Namespace(
        model="openai:gpt-4o-mini",
        provider=None,
        api_key_env="MY_K",
        session_max_turns=50,
        auto_summarize=True,
        summarizer_model=None,
        memory_type=None,
        memory_path=None,
        no_memory=False,
    )
    snap = session_started_snapshot_from_args(args)
    assert snap["effective_config"]["api_key_secret"] == "secret-from-env-flag"


def test_inject_api_key_secret_from_session_marker_sets_env_when_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("RESUME_KEY_VAR", raising=False)
    sessions = tmp_path / ".agloom" / "sessions"
    sessions.mkdir(parents=True)
    marker = sessions / "sess_inj.json"
    marker.write_text(
        json.dumps(
            {
                "effective_config": {
                    "api_key_env": "RESUME_KEY_VAR",
                    "api_key_secret": "sk-from-json",
                },
            },
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace()
    inject_api_key_secret_from_session_marker(args, marker)
    assert os.environ.get("RESUME_KEY_VAR") == "sk-from-json"


def test_inject_api_key_secret_does_not_override_nonempty_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RESUME_KEY_VAR", "live-wins")
    sessions = tmp_path / ".agloom" / "sessions"
    sessions.mkdir(parents=True)
    marker = sessions / "sess_inj2.json"
    marker.write_text(
        json.dumps(
            {
                "effective_config": {
                    "credential_env_var": "RESUME_KEY_VAR",
                    "api_key_secret": "from-json",
                },
            },
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace()
    inject_api_key_secret_from_session_marker(args, marker)
    assert os.environ.get("RESUME_KEY_VAR") == "live-wins"


def test_inject_then_merge_then_apply_api_key_flow(tmp_path, monkeypatch) -> None:
    from agloom.runtime.serve_cli import apply_api_key_env

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MY_CUSTOM", raising=False)
    sessions = tmp_path / ".agloom" / "sessions"
    sessions.mkdir(parents=True)
    marker = sessions / "sess_flow.json"
    marker.write_text(
        json.dumps(
            {
                "effective_config": {
                    "api_key_env": "MY_CUSTOM",
                    "credential_env_var": "MY_CUSTOM",
                    "api_key_secret": "sk-custom-for-openai",
                },
            },
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(session="sess_flow", api_key_env=None, model="openai:gpt-4o-mini", provider=None)
    inject_api_key_secret_from_session_marker(args, marker)
    merge_api_key_env_from_session_marker(args, marker)
    apply_api_key_env(args)
    assert os.environ.get("MY_CUSTOM") == "sk-custom-for-openai"
    assert os.environ.get("OPENAI_API_KEY") == "sk-custom-for-openai"
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
    assert ec["api_key_env"] == "MISSING_VAR"
    assert ec["api_key_env_nonempty"] is False
    assert ec["credential_env_var"] == "MISSING_VAR"
    assert ec["credential_env_var_nonempty"] is False
    assert ec["session_max_turns"] == 30
    assert ec["auto_summarize"] is False
    assert ec["summarizer_model"] == "anthropic:claude-3-5-haiku"
    assert ec["memory_type"] == "sqlite"
    assert ec["provider_resolved"] == "openai"
    assert ec["provider"] is None


def test_session_started_snapshot_nvidia_prefix_and_canonical_key(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "nim-key")
    args = argparse.Namespace(
        model="nvidia:meta/llama-4-maverick-17b-128e-instruct",
        provider=None,
        api_key_env=None,
        session_max_turns=50,
        auto_summarize=True,
        summarizer_model=None,
        memory_type="sqlite",
        memory_path=None,
        no_memory=False,
        base_url=None,
    )
    snap = session_started_snapshot_from_args(args)
    ec = snap["effective_config"]
    assert ec["provider"] is None
    assert ec["provider_resolved"] == "nvidia"
    assert ec["api_key_env"] == "NVIDIA_API_KEY"
    assert ec["api_key_env_nonempty"] is True
    assert ec["credential_env_var"] == "NVIDIA_API_KEY"
    assert ec["credential_env_var_nonempty"] is True
    assert ec["provider_primary_api_key_env"] == "NVIDIA_API_KEY"
    assert ec["provider_primary_credential_present"] is True
    cred = ec["provider_credential_env"]
    assert cred == [{"env": "NVIDIA_API_KEY", "present": True}]


def test_session_started_snapshot_llm_endpoint_from_env(monkeypatch) -> None:
    monkeypatch.delenv("VLLM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:4000/v1")
    args = argparse.Namespace(
        model="openai:gpt-4o-mini",
        provider=None,
        api_key_env=None,
        session_max_turns=50,
        auto_summarize=True,
        summarizer_model=None,
        memory_type=None,
        memory_path=None,
        no_memory=False,
        base_url=None,
    )
    snap = session_started_snapshot_from_args(args)
    ep = snap["effective_config"]["llm_endpoint"]
    assert ep["openai_compatible_base_url_from_env"] == "http://127.0.0.1:4000/v1"


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
    assert snap["effective_config"]["api_key_env"] == "OPENAI_API_KEY"
    assert snap["effective_config"]["api_key_env_nonempty"] is True
    assert snap["effective_config"]["credential_env_var"] == "OPENAI_API_KEY"
    assert snap["effective_config"]["credential_env_var_nonempty"] is True
    assert snap["effective_config"]["provider_primary_api_key_env"] == "OPENAI_API_KEY"
    assert snap["effective_config"]["provider_primary_credential_present"] is True
    assert snap["effective_config"]["llm_resolution"] == "env_auto"


def test_session_started_snapshot_sampling_penalties_and_max_tokens_override() -> None:
    args = argparse.Namespace(
        model="openai:gpt-4o-mini",
        provider=None,
        api_key_env=None,
        session_max_turns=50,
        auto_summarize=True,
        summarizer_model=None,
        memory_type=None,
        memory_path=None,
        no_memory=False,
        max_tokens=2048,
        frequency_penalty=0.5,
        presence_penalty=-0.25,
    )
    snap = session_started_snapshot_from_args(args)
    ec = snap["effective_config"]
    assert ec["max_tokens"] == 2048
    assert ec["frequency_penalty"] == 0.5
    assert ec["presence_penalty"] == -0.25


def test_merge_api_key_env_from_session_marker(tmp_path: Path) -> None:
    sessions = tmp_path / ".agloom" / "sessions"
    sessions.mkdir(parents=True)
    marker = sessions / "sess_resume_test.json"
    marker.write_text(
        json.dumps(
            {
                "session_id": "sess_resume_test",
                "effective_config": {
                    "credential_env_var": "MY_NV_KEY",
                    "provider_primary_api_key_env": "NVIDIA_API_KEY",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(session="sess_resume_test", api_key_env=None, model="nvidia:x", provider=None)
    merge_api_key_env_from_session_marker(args, marker)
    assert args.api_key_env == "MY_NV_KEY"


def test_merge_api_key_env_prefers_api_key_env_in_marker(tmp_path: Path) -> None:
    sessions = tmp_path / ".agloom" / "sessions"
    sessions.mkdir(parents=True)
    marker = sessions / "sess_a.json"
    marker.write_text(
        json.dumps(
            {
                "effective_config": {
                    "api_key_env": "CUSTOM_A",
                    "credential_env_var": "CUSTOM_B",
                },
            },
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(session="sess_a", api_key_env=None, model="openai:gpt-4o", provider=None)
    merge_api_key_env_from_session_marker(args, marker)
    assert args.api_key_env == "CUSTOM_A"


def test_merge_api_key_env_cli_wins(tmp_path: Path) -> None:
    sessions = tmp_path / ".agloom" / "sessions"
    sessions.mkdir(parents=True)
    marker = sessions / "sess_b.json"
    marker.write_text(
        json.dumps({"effective_config": {"credential_env_var": "FROM_DISK"}}),
        encoding="utf-8",
    )
    args = argparse.Namespace(session="sess_b", api_key_env="CLI_WINS", model="openai:gpt-4o", provider=None)
    merge_api_key_env_from_session_marker(args, marker)
    assert args.api_key_env == "CLI_WINS"


def test_skills_disk_mirror_defaults_to_dot_agloom_skills(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    from agloom.runtime.serve_cli import skills_disk_mirror_from_args

    p = skills_disk_mirror_from_args(argparse.Namespace(skills_dir=None))
    assert p == (tmp_path / ".agloom" / "skills").resolve()
