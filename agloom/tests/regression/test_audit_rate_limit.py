"""TransportManager rate_limit enforcement."""

import asyncio
import time

import pytest

from agloom.transport.manager import TransportManager, TransportPolicy


@pytest.mark.asyncio
async def test_transport_manager_rate_limit_throttles():
    tm = TransportManager(TransportPolicy(rate_limit=5.0))
    t0 = time.perf_counter()
    await tm.acquire_llm_slot()
    await tm.acquire_llm_slot()
    elapsed = time.perf_counter() - t0
    assert elapsed >= 0.15
