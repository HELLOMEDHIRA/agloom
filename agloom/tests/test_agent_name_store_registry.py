"""Agent name ↔ LongTermStore tracking (no ``id(store)`` false positives)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from agloom.memory.store import LongTermStore
from agloom.unified_agent import _register_agent_name, _unregister_agent_name


def test_duplicate_agent_name_warns_same_store_not_different_store(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="agloom.unified_agent")
    backend_a = MagicMock()
    backend_b = MagicMock()
    store_a = LongTermStore(backend_a)
    store_b = LongTermStore(backend_b)

    _register_agent_name("shared", store_a)
    _register_agent_name("shared", store_a)
    assert any("Multiple agents named 'shared'" in r.message for r in caplog.records)

    caplog.clear()
    _unregister_agent_name("shared", store_a)
    _unregister_agent_name("shared", store_a)

    _register_agent_name("shared", store_b)
    assert not any("Multiple agents" in r.message for r in caplog.records)
    _unregister_agent_name("shared", store_b)


def test_no_store_never_warns_on_duplicate(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="agloom.unified_agent")
    _register_agent_name("solo", None)
    _register_agent_name("solo", None)
    assert not any("Multiple agents" in r.message for r in caplog.records)
    _unregister_agent_name("solo", None)
    _unregister_agent_name("solo", None)
