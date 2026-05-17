"""Shared pytest hooks for the agloom test suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session", autouse=True)
def _shutdown_qdrant_thread_pool_after_tests() -> Iterator[None]:
    yield
    try:
        from agloom.cache import shutdown_qdrant_pool

        shutdown_qdrant_pool(wait=False, cancel_futures=True)
    except ImportError:
        pass
