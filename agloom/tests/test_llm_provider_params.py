"""Unit tests for :mod:`agloom.llm.llm_provider_params`."""

from __future__ import annotations

import pytest

from agloom.llm.llm_provider_params import normalize_provider_slug, spread_llm_options_for_provider


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Google_GenAI", "google"),
        ("gemini", "google"),
        ("mistral", "mistralai"),
        ("vertex_ai", "google_vertexai"),
        ("anthropic_bedrock", "bedrock"),
        ("groq", "groq"),
    ],
)
def test_normalize_provider_slug_aliases(raw: str, expected: str) -> None:
    assert normalize_provider_slug(raw) == expected


def test_spread_llm_options_filters_unknown_keys() -> None:
    out = spread_llm_options_for_provider(
        "openai",
        {"temperature": 0.2, "made_up_flag": True, "max_tokens": 128},
    )
    assert out["temperature"] == 0.2
    assert out["max_tokens"] == 128
    assert "made_up_flag" not in out


def test_spread_llm_timeout_alias_openai_family() -> None:
    out = spread_llm_options_for_provider("openai", {"timeout": 30.0})
    assert out == {"request_timeout": 30.0}


def test_spread_llm_groq_timeout_alias() -> None:
    out = spread_llm_options_for_provider("groq", {"timeout": 12.0})
    assert out == {"request_timeout": 12.0}
