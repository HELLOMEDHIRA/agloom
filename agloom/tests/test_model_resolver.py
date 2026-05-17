"""Unit tests for pure helpers in :mod:`agloom.llm.model_resolver`."""

from __future__ import annotations

import pytest

from agloom.llm.model_resolver import (
    _resolve_anthropic_model_id,
    augment_patch_api_keys_from_env,
    provider_slug_token_valid,
    split_provider_prefix,
)
from agloom.llm.provider_registry import cli_auto_detect_rows


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


def test_cli_auto_detect_includes_nvidia() -> None:
    slugs = [row[0] for row in cli_auto_detect_rows()]
    assert "nvidia" in slugs


@pytest.mark.parametrize(
    "model_id",
    [
        "claude-3-5-sonnet-20241022",
        "claude-3-5-sonnet-20250219",
        "claude-3-7-sonnet-20250219",
        "claude-sonnet-4-20250514",
    ],
)
def test_resolve_anthropic_model_id_passes_through_dated_ids(model_id: str) -> None:
    assert _resolve_anthropic_model_id(model_id) == model_id


def test_resolve_anthropic_model_id_maps_legacy_shorthand_only(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGLOOM_ANTHROPIC_LEGACY_SHORTHAND_ALIASES", "1")
    caplog.set_level("WARNING", logger="agloom.llm.model_resolver")
    assert _resolve_anthropic_model_id("claude-3-sonnet") == "claude-3-5-sonnet-20241022"
    assert "claude-3-sonnet" in caplog.text
    assert "claude-3-5-sonnet-20241022" in caplog.text


def test_resolve_anthropic_model_id_does_not_rewrite_versioned_sonnet() -> None:
    assert _resolve_anthropic_model_id("claude-3-5-sonnet-20250219") == "claude-3-5-sonnet-20250219"
