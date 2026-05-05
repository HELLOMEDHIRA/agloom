"""Tests for CLI model auto-resolution from API keys."""

from __future__ import annotations

import pytest

from agloom_cli import config as cfg
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


def test_resolve_model_env_skips_openai_model_id_when_extra_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENAI_MODEL_ID must not win when OpenAI extra is absent but GROQ_MODEL_ID works."""
    monkeypatch.setenv("OPENAI_MODEL_ID", "gpt-4o")
    monkeypatch.setenv("GROQ_MODEL_ID", "meta-llama/llama-4-scout-17b-16e-instruct")
    monkeypatch.setattr(
        cfg,
        "create_default_config",
        lambda: {"ai": {"model": "auto"}},
    )

    def fake_get_model(model_id: str, **kwargs: object) -> object:
        if model_id == "gpt-4o":
            raise mr.MissingProviderDependency("openai", "'agloom[openai]'")
        if model_id == "meta-llama/llama-4-scout-17b-16e-instruct":
            return "groq-ok"
        raise AssertionError(model_id)

    monkeypatch.setattr(mr, "get_model", fake_get_model)
    assert cfg.resolve_model("auto") == "groq-ok"


def test_require_env_raises_for_missing_groq_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(mr.MissingProviderApiKey, match="GROQ_API_KEY"):
        mr._require_env("GROQ_API_KEY", for_provider="Groq")


def test_resolve_model_config_gpt_falls_back_to_key_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pinned ``ai.model: gpt-4o`` should not hard-fail when only other providers are installed."""
    monkeypatch.setattr(
        cfg,
        "create_default_config",
        lambda: {"ai": {"model": "gpt-4o"}},
    )
    for var in (
        "OPENAI_MODEL_ID",
        "GROQ_MODEL_ID",
        "ANTHROPIC_MODEL_ID",
        "GOOGLE_MODEL_ID",
        "GEMINI_MODEL_ID",
        "MISTRAL_MODEL_ID",
        "XAI_MODEL_ID",
    ):
        monkeypatch.delenv(var, raising=False)

    def fake_get_model(model_id: str, **kwargs: object) -> object:
        if model_id == "gpt-4o":
            raise mr.MissingProviderDependency("openai", "'agloom[openai]'")
        raise AssertionError(model_id)

    monkeypatch.setattr(mr, "get_model", fake_get_model)
    monkeypatch.setattr(mr, "try_resolve_llm_from_api_keys", lambda: "from-keys")
    assert cfg.resolve_model("auto") == "from-keys"
