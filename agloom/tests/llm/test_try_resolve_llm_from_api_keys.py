"""``try_resolve_llm_from_api_keys`` wires registry default models to the correct provider."""

from __future__ import annotations

from typing import Any

import pytest

from agloom.llm import model_resolver as mr


def test_auto_detect_passes_provider_for_slashy_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """NVIDIA (and similar) defaults use ``org/model`` ids; resolver must not treat them as ambiguous."""
    calls: list[tuple[str, str | None]] = []

    def fake_get_model(model_id: str, *, provider: str | None = None, **kwargs: Any) -> object:
        calls.append((model_id, provider))
        return object()

    monkeypatch.setattr(mr, "get_model", fake_get_model)
    monkeypatch.setattr(
        mr,
        "_usable_provider_triples",
        lambda: ([("nvidia", "NVIDIA NIM", "meta/llama3-70b-instruct")], []),
    )
    monkeypatch.delenv("AGLOOM_PROVIDER", raising=False)

    mr.try_resolve_llm_from_api_keys(interactive=False)

    assert calls == [("meta/llama3-70b-instruct", "nvidia")]


def test_agloom_provider_match_passes_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_get_model(model_id: str, *, provider: str | None = None, **kwargs: Any) -> object:
        calls.append((model_id, provider))
        return object()

    monkeypatch.setattr(mr, "get_model", fake_get_model)
    monkeypatch.setattr(
        mr,
        "_usable_provider_triples",
        lambda: (
            [
                ("openai", "OpenAI", "gpt-4o"),
                ("nvidia", "NVIDIA NIM", "meta/llama3-70b-instruct"),
            ],
            [],
        ),
    )
    monkeypatch.setenv("AGLOOM_PROVIDER", "nvidia")

    mr.try_resolve_llm_from_api_keys(interactive=False)

    assert calls == [("meta/llama3-70b-instruct", "nvidia")]
