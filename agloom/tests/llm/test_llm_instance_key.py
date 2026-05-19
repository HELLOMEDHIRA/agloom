"""LlmInstanceKey is used when chat models are not weakdict-hashable."""

from __future__ import annotations

from agloom.llm.instance_key import LlmInstanceKey, llm_cache_key
from agloom.llm_utils import _circuit_breaker_for, _structured_inner_get_or_create


class _UnhashableChat:
    def __eq__(self, other: object) -> bool:
        return self is other


def test_llm_cache_key_uses_instance_key_for_unhashable() -> None:
    llm = _UnhashableChat()
    key = llm_cache_key(llm)
    assert isinstance(key, LlmInstanceKey)
    assert key.object_id == id(llm)


def test_circuit_breaker_unhashable_reuses_same_breaker() -> None:
    llm = _UnhashableChat()
    assert _circuit_breaker_for(llm) is _circuit_breaker_for(llm)


def test_structured_cache_unhashable_does_not_crash() -> None:
    from pydantic import BaseModel

    class _S(BaseModel):
        ok: bool = True

    llm = _UnhashableChat()
    inner = _structured_inner_get_or_create(llm)
    assert inner is _structured_inner_get_or_create(llm)
