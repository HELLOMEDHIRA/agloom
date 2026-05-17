"""Circuit breaker uses typed exceptions, not ``RuntimeError`` message sniffing."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from langchain_core.messages import HumanMessage

from agloom.llm_utils import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitBreakerHalfOpenBusy,
    CircuitBreakerOpen,
    _circuit_breaker_for,
    _try_invoke,
)


def test_circuit_breaker_exception_types() -> None:
    open_exc = CircuitBreakerOpen(threshold=3, recovery_s=30.0)
    assert isinstance(open_exc, CircuitBreakerError)
    assert "OPEN" in str(open_exc)
    busy = CircuitBreakerHalfOpenBusy("probe busy")
    assert isinstance(busy, CircuitBreakerError)


@pytest.mark.asyncio
async def test_try_invoke_handles_circuit_breaker_open(monkeypatch: pytest.MonkeyPatch) -> None:
    br = CircuitBreaker(failure_threshold=1, recovery_timeout=3600.0)
    monkeypatch.setattr("agloom.llm_utils.DEFAULT_CIRCUIT_BREAKER", br)

    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=ValueError("provider"))
    errors: list[str] = []

    r1 = await _try_invoke(structured, [], 1.0, None, "", "first", errors)
    assert r1 is None
    assert br.state == "open"

    structured.ainvoke = AsyncMock(return_value={"ok": True})
    errors.clear()
    r2 = await _try_invoke(structured, [], 1.0, None, "", "second", errors)
    assert r2 is None
    assert errors
    assert "CircuitBreakerOpen" in errors[0]


@pytest.mark.asyncio
async def test_try_invoke_propagates_half_open_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    """HALF-OPEN probe contention must not be swallowed as a generic failed strategy."""

    class BusyBreaker:
        async def __aenter__(self) -> BusyBreaker:
            raise CircuitBreakerHalfOpenBusy("contended")

        async def __aexit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr("agloom.llm_utils.DEFAULT_CIRCUIT_BREAKER", BusyBreaker())

    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value={"ok": True})
    errors: list[str] = []

    with pytest.raises(CircuitBreakerHalfOpenBusy):
        await _try_invoke(structured, [], 1.0, None, "", "half", errors)
    structured.ainvoke.assert_not_awaited()
    assert errors == []


@pytest.mark.asyncio
async def test_robust_structured_call_retries_half_open_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import BaseModel

    from agloom.llm_utils import robust_structured_call

    class Mini(BaseModel):
        v: int = 1

    calls = 0

    async def fake_try_invoke(*args: object, **kwargs: object) -> Mini:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise CircuitBreakerHalfOpenBusy("contended")
        return Mini(v=42)

    monkeypatch.setattr("agloom.llm_utils._try_invoke", fake_try_invoke)
    monkeypatch.setattr("agloom.llm_utils._llm_skips_json_schema_mode", lambda _llm: True)
    monkeypatch.setattr("agloom.llm_utils._env_skip_json_schema_first", lambda: True)

    llm = MagicMock()
    monkeypatch.setattr("agloom.llm_utils._build_structured", lambda *_a, **_k: llm)

    out = await robust_structured_call(
        llm,
        Mini,
        [HumanMessage(content="hi")],
        max_retries=1,
        timeout=1.0,
        caller="test",
    )
    assert out is not None and out.v == 42
    assert calls >= 3


@pytest.mark.asyncio
async def test_circuit_breakers_are_isolated_per_llm_instance() -> None:
    """Failures on one LLM must not open the breaker for another."""
    llm_a = MagicMock(name="llm_a")
    llm_b = MagicMock(name="llm_b")
    br_a = _circuit_breaker_for(llm_a)
    br_b = _circuit_breaker_for(llm_b)
    assert br_a is not br_b

    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=ValueError("fail"))
    errors: list[str] = []

    for _ in range(5):
        await _try_invoke(structured, [], 1.0, None, "", "a1", errors, circuit_breaker=br_a)
    assert br_a.state == "open"
    assert br_b.state == "closed"

    structured.ainvoke = AsyncMock(return_value={"v": 1})
    errors.clear()
    out = await _try_invoke(
        structured,
        [],
        1.0,
        None,
        "",
        "b1",
        errors,
        circuit_breaker=br_b,
    )
    assert out == {"v": 1}
    assert errors == []


@pytest.mark.asyncio
async def test_circuit_breaker_ignores_cancelled_error() -> None:
    br = CircuitBreaker(failure_threshold=1, recovery_timeout=3600.0)
    with pytest.raises(asyncio.CancelledError):
        async with br:
            raise asyncio.CancelledError()
    assert br.state == "closed"


def test_circuit_breaker_id_fallback_isolates_bare_objects() -> None:
    """When weakref is impossible (e.g. bare ``object()`` on 3.14), use ``id(llm)`` keys."""
    a = object()
    b = object()
    assert _circuit_breaker_for(a) is not _circuit_breaker_for(b)
