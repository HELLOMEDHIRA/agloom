"""Tests for CLI model auto-resolution from API keys."""

from __future__ import annotations

import os

import pytest

from agloom_cli import config as cfg
from agloom_cli import model_resolver as mr


def test_split_provider_prefix_groq() -> None:
    p, rest = mr.split_provider_prefix("groq:meta-llama/llama-4-scout-17b-16e-instruct")
    assert p == "groq"
    assert rest == "meta-llama/llama-4-scout-17b-16e-instruct"


def test_split_provider_prefix_invalid_token_preserved() -> None:
    """Tokens with spaces or leading digits are not ``provider:model`` splits."""
    p, rest = mr.split_provider_prefix("not a provider:something")
    assert p is None
    assert rest == "not a provider:something"
    p2, rest2 = mr.split_provider_prefix("9bad:model")
    assert p2 is None
    assert rest2 == "9bad:model"


def test_split_provider_prefix_https_preserved() -> None:
    p, rest = mr.split_provider_prefix("https://example.com/v1")
    assert p is None
    assert rest == "https://example.com/v1"


def test_split_provider_prefix_arbitrary_langchain_provider() -> None:
    p, rest = mr.split_provider_prefix("cohere:command-r-plus")
    assert p == "cohere"
    assert rest == "command-r-plus"


def test_split_provider_prefix_litellm_rest_preserves_slashes() -> None:
    p, rest = mr.split_provider_prefix("litellm:groq/llama-3.3-70b-versatile")
    assert p == "litellm"
    assert rest == "groq/llama-3.3-70b-versatile"


def test_split_provider_prefix_lc_preserves_provider_colon() -> None:
    """Everything after ``lc:`` is passed to ``init_chat_model`` (may contain multiple ``:``)."""
    p, rest = mr.split_provider_prefix("lc:openai:gpt-4o-mini")
    assert p == "lc"
    assert rest == "openai:gpt-4o-mini"


def test_split_provider_prefix_init_alias() -> None:
    p, rest = mr.split_provider_prefix("init:groq:meta-llama/foo")
    assert p == "init"
    assert rest == "groq:meta-llama/foo"


def test_get_model_litellm_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_litellm(model_id: str, **kwargs: object) -> str:
        return f"litellm:{model_id}:{kwargs.get('temperature', -1)}"

    monkeypatch.setattr(mr, "_get_litellm_model", fake_litellm)
    assert mr.get_model("litellm:groq/x") == "litellm:groq/x:-1"


def test_get_model_lc_prefix_delegates_to_init(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_init(model: str, **kwargs: object) -> str:
        return f"lc:{model}"

    monkeypatch.setattr(mr, "_init_chat_model_unified", fake_init)
    assert mr.get_model("lc:openai:gpt-4o") == "lc:openai:gpt-4o"


def test_get_model_openrouter_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_init(model: str, *, model_provider: str | None = None, **kwargs: object) -> dict[str, object]:
        seen["model"] = model
        seen["model_provider"] = model_provider
        return seen

    monkeypatch.setattr(mr, "_init_chat_model_unified", fake_init)
    out = mr.get_model("openrouter:anthropic/claude-3.5-sonnet")
    assert out["model"] == "anthropic/claude-3.5-sonnet"
    assert out["model_provider"] == "openrouter"


def test_ambiguous_slash_requires_disambiguation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGLOOM_PROVIDER", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    with pytest.raises(ValueError, match="groq:"):
        mr.get_model("meta-llama/foo")


def test_slash_resolves_groq_when_only_groq_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    def fake_groq(model_id: str, **kwargs: object) -> str:
        return f"groq:{model_id}"

    monkeypatch.setattr(mr, "_get_groq_model", fake_groq)
    assert mr.get_model("meta-llama/foo") == "groq:meta-llama/foo"


def test_try_resolve_skips_first_provider_when_extra_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENAI_API_KEY alone must not block GROQ when only Groq integration is usable."""

    monkeypatch.setattr(mr, "_integration_importable", lambda slug: slug == "groq")

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
    monkeypatch.setattr(mr, "_integration_importable", lambda _slug: False)
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

    def fake_get_model(model_id: str, **kwargs: object) -> object:
        if model_id == "gpt-4o":
            raise mr.MissingProviderDependency("openai", "'agloom[openai]'")
        if model_id == "meta-llama/llama-4-scout-17b-16e-instruct":
            return "groq-ok"
        raise AssertionError(model_id)

    monkeypatch.setattr(mr, "get_model", fake_get_model)
    assert cfg.resolve_model("auto", config={"ai": {"model": "auto"}}) == "groq-ok"


def test_try_resolve_agloom_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mr, "_integration_importable", lambda slug: slug in ("openai", "groq"))
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("GROQ_API_KEY", "y")
    monkeypatch.setenv("AGLOOM_PROVIDER", "groq")
    seen: list[str] = []

    def fake_get_model(model_id: str, **kwargs: object) -> str:
        seen.append(model_id)
        return f"ok:{model_id}"

    monkeypatch.setattr(mr, "get_model", fake_get_model)
    out = mr.try_resolve_llm_from_api_keys(interactive=False)
    assert out is not None and out.startswith("ok:")
    assert "llama" in seen[-1]


def test_require_env_raises_for_missing_groq_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(mr.MissingProviderApiKey, match="GROQ_API_KEY"):
        mr._require_env("GROQ_API_KEY", for_provider="Groq")


def test_resolve_model_config_gpt_falls_back_to_key_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pinned ``ai.model: gpt-4o`` should not hard-fail when only other providers are installed."""
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
    monkeypatch.setattr(mr, "try_resolve_llm_from_api_keys", lambda **kwargs: "from-keys")
    assert cfg.resolve_model("auto", config={"ai": {"model": "gpt-4o"}}) == "from-keys"


def test_resolve_model_yaml_api_keys_applied_during_get_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    captured: dict[str, str | None] = {}

    def fake_get_model(model_id: str, **kwargs: object) -> str:
        captured["during"] = os.environ.get("GROQ_API_KEY")
        return "ok"

    monkeypatch.setattr(mr, "get_model", fake_get_model)
    out = cfg.resolve_model(
        "groq:meta-llama/llama-4-scout-17b-16e-instruct",
        config={"ai": {"api_keys": {"GROQ_API_KEY": "key-from-yaml"}}},
    )
    assert out == "ok"
    assert captured["during"] == "key-from-yaml"
    assert os.environ.get("GROQ_API_KEY") is None


def test_get_model_unknown_provider_slug_uses_init_chat_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_init(model: str, *, model_provider: str | None = None, **kwargs: object) -> str:
        return f"init:{model_provider}:{model}"

    monkeypatch.setattr(mr, "_init_chat_model_unified", fake_init)
    assert mr.get_model("bedrock:us.anthropic.claude-3-5-sonnet") == "init:bedrock:us.anthropic.claude-3-5-sonnet"
