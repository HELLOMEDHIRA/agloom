"""Shared pytest hooks for the agloom test suite."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "provider_probe: optional LangChain provider packages (set AGLOOM_PROVIDER_PROBE=1)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("AGLOOM_PROVIDER_PROBE", "").strip().lower() in ("1", "true", "yes", "on"):
        return
    if config.getoption("-m", default=None):
        return
    skip = pytest.mark.skip(reason="provider probes skipped (set AGLOOM_PROVIDER_PROBE=1)")
    for item in items:
        if "provider_probe" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def _shutdown_qdrant_thread_pool_after_tests() -> Iterator[None]:
    yield
    try:
        from agloom.cache import shutdown_qdrant_pool

        shutdown_qdrant_pool(wait=False, cancel_futures=True)
    except ImportError:
        pass
