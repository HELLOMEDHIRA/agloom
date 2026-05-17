"""Unprefixed ``org/model`` ids route via :func:`agloom.llm.model_resolver._route_slash_model`."""

from __future__ import annotations

import pytest

from agloom.llm import model_resolver


def test_deepseek_slash_model_routes_with_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    calls: list[tuple[str, str]] = []

    def _fake_get_by_provider(slug: str, model_id: str, **kwargs: object) -> str:
        calls.append((slug, model_id))
        return f"model:{slug}"

    monkeypatch.setattr(model_resolver, "_get_by_provider", _fake_get_by_provider)
    monkeypatch.setattr(
        model_resolver,
        "_integration_importable",
        lambda slug: slug == "deepseek",
    )

    out = model_resolver.get_model("deepseek/deepseek-chat")
    assert out == "model:deepseek"
    assert calls == [("deepseek", "deepseek/deepseek-chat")]
