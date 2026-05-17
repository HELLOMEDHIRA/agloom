"""Structured-output builder cache is keyed on the LLM object, not ``id(llm)``."""

from __future__ import annotations

from unittest.mock import MagicMock

from pydantic import BaseModel

from agloom.llm_utils import _build_structured


class _Schema(BaseModel):
    n: int = 0


def test_build_structured_caches_per_llm_instance() -> None:
    llm_a = MagicMock()
    llm_a.with_structured_output = MagicMock(return_value="runner-a")

    assert _build_structured(llm_a, _Schema, "json_schema") == "runner-a"
    assert _build_structured(llm_a, _Schema, "json_schema") == "runner-a"
    llm_a.with_structured_output.assert_called_once()

    llm_b = MagicMock()
    llm_b.with_structured_output = MagicMock(return_value="runner-b")
    assert _build_structured(llm_b, _Schema, "json_schema") == "runner-b"
    llm_b.with_structured_output.assert_called_once()


def test_build_structured_caches_negative_result() -> None:
    llm = MagicMock()
    llm.with_structured_output = MagicMock(side_effect=NotImplementedError)
    assert _build_structured(llm, _Schema, "json_schema") is None
    assert _build_structured(llm, _Schema, "json_schema") is None
    llm.with_structured_output.assert_called_once()
