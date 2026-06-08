"""Groq structured-output allowlist includes documented prefixes."""

from __future__ import annotations

from types import SimpleNamespace

from agloom.llm_utils import _groq_allows_json_schema_first


class _FakeGroq:
    pass


def test_groq_prefix_allows_new_llama4_model(monkeypatch) -> None:
    monkeypatch.setattr(
        "agloom.llm_utils._is_groq_chat_llm",
        lambda _llm: True,
    )
    llm = SimpleNamespace(model_name="meta-llama/llama-4-maverick-17b-128e-instruct")
    assert _groq_allows_json_schema_first(llm) is True


def test_groq_unknown_model_still_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "agloom.llm_utils._is_groq_chat_llm",
        lambda _llm: True,
    )
    llm = SimpleNamespace(model_name="llama-3.3-70b-versatile")
    assert _groq_allows_json_schema_first(llm) is False
