"""Tests for CLI model auto-resolution from API keys."""

from __future__ import annotations

import pytest

from agloom_cli import model_resolver as mr


def test_try_resolve_skips_first_provider_when_extra_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENAI_API_KEY alone must not block GROQ when only Groq extra is installed."""

    def fake_get_model(model_id: str, **kwargs: object) -> object:
        if model_id == "gpt-4o":
            raise mr.MissingProviderDependency("openai", "'agloom[openai]'")
        if model_id == "meta-llama/llama-4-scout-17b-16e-instruct":
            return object()
        raise AssertionError(f"unexpected model_id {model_id!r}")

    monkeypatch.setattr(mr, "get_model", fake_get_model)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")

    out = mr.try_resolve_llm_from_api_keys()
    assert out is not None


def test_try_resolve_multiple_missing_extras_aggregate(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_model(model_id: str, **kwargs: object) -> object:
        if model_id == "gpt-4o":
            raise mr.MissingProviderDependency("openai", "'agloom[openai]'")
        if model_id == "meta-llama/llama-4-scout-17b-16e-instruct":
            raise mr.MissingProviderDependency("groq", "'agloom[groq]'")
        raise AssertionError(model_id)

    monkeypatch.setattr(mr, "get_model", fake_get_model)
    monkeypatch.setenv("OPENAI_API_KEY", "a")
    monkeypatch.setenv("GROQ_API_KEY", "b")

    with pytest.raises(mr.MissingProviderDependency) as ei:
        mr.try_resolve_llm_from_api_keys()
    assert ei.value.extra == "multiple"
    assert "openai" in str(ei.value)
    assert "groq" in str(ei.value)
