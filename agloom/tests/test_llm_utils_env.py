"""Tests for ``llm_utils`` environment toggles."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agloom.llm_utils import robust_structured_call


class _Mini(BaseModel):
    x: int = 1


@pytest.mark.asyncio
async def test_agloom_skip_json_schema_env_skips_first_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGLOOM_SKIP_JSON_SCHEMA", "1")
    calls: list[str | None] = []

    def fake_build_structured(llm, schema, *, method=None):
        calls.append(method)
        return None

    monkeypatch.setattr("agloom.llm_utils._build_structured", fake_build_structured)

    async def no_fallback(*a, **k):
        return None

    monkeypatch.setattr("agloom.llm_utils._try_raw_json_fallback", no_fallback)

    class DummyLLM:
        pass

    await robust_structured_call(DummyLLM(), _Mini, [], max_retries=0, timeout=0.1, caller="test")
    assert "json_schema" not in calls
