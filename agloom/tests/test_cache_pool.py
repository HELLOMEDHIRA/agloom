"""Qdrant cache thread pool must be lazy and shut down cleanly."""

from __future__ import annotations

import pytest

pytest.importorskip("google.protobuf")

from agloom import cache as cache_mod


def test_qdrant_pool_lazy_and_shutdown() -> None:
    cache_mod.shutdown_qdrant_pool(wait=True)
    assert cache_mod._pool is None

    pool_a = cache_mod._get_qdrant_pool()
    pool_b = cache_mod._get_qdrant_pool()
    assert pool_a is pool_b

    cache_mod.shutdown_qdrant_pool(wait=True)
    assert cache_mod._pool is None
    assert not cache_mod._executor_alive(pool_a)

    pool_c = cache_mod._get_qdrant_pool()
    assert pool_c is not pool_a
    cache_mod.shutdown_qdrant_pool(wait=True)
