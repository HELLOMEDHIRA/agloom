"""Model string parsing: ``split_provider_prefix`` and provider-prefix normalization."""

from __future__ import annotations

import pytest

from agloom.llm.llm_provider_params import normalize_provider_slug
from agloom.llm.model_resolver import (
    get_model,
    split_provider_prefix,
    suggest_typo_provider_slug,
)


@pytest.mark.parametrize(
    ("spec", "expected_pref", "expected_rest"),
    [
        ("openai:gpt-4o", "openai", "gpt-4o"),
        (
            "groq:meta-llama/llama-3.3-70b-versatile",
            "groq",
            "meta-llama/llama-3.3-70b-versatile",
        ),
        (
            "litellm:groq/llama-3.3-70b-versatile",
            "litellm",
            "groq/llama-3.3-70b-versatile",
        ),
        (
            "openrouter:anthropic/claude-3.5-sonnet",
            "openrouter",
            "anthropic/claude-3.5-sonnet",
        ),
        ("lc:openai:gpt-4o", "lc", "openai:gpt-4o"),
        (
            "init:groq:meta-llama/llama-3.3-70b-versatile",
            "init",
            "groq:meta-llama/llama-3.3-70b-versatile",
        ),
        (
            "bedrock:anthropic.claude-3-5-sonnet-20241022-v2:0",
            "bedrock",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
        ),
        ("google_vertexai:gemini-2.0-flash", "google_vertexai", "gemini-2.0-flash"),
    ],
)
def test_split_provider_prefix(spec: str, expected_pref: str, expected_rest: str) -> None:
    pref, rest = split_provider_prefix(spec)
    assert pref == expected_pref
    assert rest == expected_rest


@pytest.mark.parametrize(
    "spec",
    [
        "GROQ:meta-llama/llama-3.3-70b-versatile",
        "Groq:meta-llama/llama-3.3-70b-versatile",
    ],
)
def test_split_provider_prefix_case_insensitive(spec: str) -> None:
    pref, rest = split_provider_prefix(spec)
    assert pref == "groq"
    assert rest == "meta-llama/llama-3.3-70b-versatile"


def test_split_no_prefix_bare_model() -> None:
    assert split_provider_prefix("gpt-4o") == (None, "gpt-4o")


def test_split_uri_not_treated_as_prefix() -> None:
    assert split_provider_prefix("https://example.com") == (None, "https://example.com")


def test_unknown_provider_typo_suggests_groq() -> None:
    assert suggest_typo_provider_slug("gorq") == "groq"


def test_exact_slug_no_typo_suggestion() -> None:
    assert suggest_typo_provider_slug("groq") is None


def test_normalize_merge_openai() -> None:
    pref, rest = split_provider_prefix("openai:gpt-4o")
    merged = normalize_provider_slug(pref) if pref else ""
    assert merged == "openai"
    assert rest == "gpt-4o"


def test_get_model_rejects_obvious_provider_typo_before_sdk() -> None:
    with pytest.raises(ValueError, match=r"did you mean 'groq'"):
        get_model("gorq:meta-llama/llama-3.3-70b-versatile")
