"""Unit tests for pure helpers in :mod:`agloom.llm.model_resolver`."""

from __future__ import annotations

import pytest

from agloom.llm.model_resolver import (
    augment_patch_api_keys_from_env,
    provider_slug_token_valid,
    split_provider_prefix,
)


@pytest.mark.parametrize(
    ("spec", "prefix", "rest"),
    [
        ("groq:llama-3.1-8b", "groq", "llama-3.1-8b"),
        ("lc:openai:gpt-4o", "lc", "openai:gpt-4o"),
        ("init:xai:grok", "init", "xai:grok"),
        ("https://example.com/v1", None, "https://example.com/v1"),
        ("no-prefix-model", None, "no-prefix-model"),
        ("bad token:rest", None, "bad token:rest"),
    ],
)
def test_split_provider_prefix(spec: str, prefix: str | None, rest: str) -> None:
    assert split_provider_prefix(spec) == (prefix, rest)


@pytest.mark.parametrize(
    ("slug", "ok"),
    [
        ("groq", True),
        ("open_ai", True),
        ("9bad", False),
        ("", False),
    ],
)
def test_provider_slug_token_valid(slug: str, ok: bool) -> None:
    assert provider_slug_token_valid(slug) is ok


def test_augment_patch_api_keys_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    patch: dict = {"model": "gpt-4o-mini", "provider": "openai"}
    out = augment_patch_api_keys_from_env(patch)
    assert out["api_keys"]["OPENAI_API_KEY"] == "sk-test"


def test_augment_patch_skips_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    patch: dict = {"model": "gpt-4o-mini", "provider": "openai"}
    out = augment_patch_api_keys_from_env(patch)
    assert "api_keys" not in out or not out.get("api_keys")
