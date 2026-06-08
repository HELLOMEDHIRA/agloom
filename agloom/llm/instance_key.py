"""Stable identity for LLM client instances used in process-local caches."""

from __future__ import annotations

import weakref
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class LlmInstanceKey:
    """Hashable cache key when a chat model is not weakref/hashable."""

    provider: str
    model: str
    object_id: int

    @classmethod
    def from_llm(cls, llm: Any) -> LlmInstanceKey:
        provider = type(llm).__module__.split(".", 2)[-1] if llm is not None else ""
        model = (
            getattr(llm, "model_name", None)
            or getattr(llm, "model", None)
            or getattr(llm, "model_id", None)
            or ""
        )
        return cls(
            provider=provider or type(llm).__name__,
            model=str(model or ""),
            object_id=id(llm),
        )


def llm_cache_key(llm: Any) -> Any:
    """Return *llm* when it can index ``WeakKeyDictionary``; else :class:`LlmInstanceKey`."""
    from agloom.llm_utils import llm_weak_dict_key_ok

    if llm_weak_dict_key_ok(llm):
        return llm
    return LlmInstanceKey.from_llm(llm)


def touch_llm_weakref(llm: Any) -> None:
    """Ensure weakref is possible (raises nothing)."""
    try:
        weakref.ref(llm)
    except TypeError:
        pass
