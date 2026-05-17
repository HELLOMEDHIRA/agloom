"""Regression tests for audit-driven hardening (multimodal, token usage, delegation, logging)."""

from __future__ import annotations

import uuid

import pytest

from agloom.delegation import BackgroundDelegationManager
from agloom.logging_utils import get_logger
from agloom.models import _extract_token_usage
from agloom.multimodal import model_id_supports_vision


def test_model_id_supports_vision_no_false_positive_on_no_vision_slug() -> None:
    # Previously a bare ``\"vision\"`` substring matched ``no-vision``.
    assert model_id_supports_vision("vendor/no-vision-model-v1") is False


def test_model_id_supports_vision_gpt4o_family() -> None:
    assert model_id_supports_vision("openai/gpt-4o-mini") is True


def test_model_id_supports_vision_regex_path() -> None:
    assert model_id_supports_vision("custom-gpt-4.1-vision-preview") is True


def test_extract_token_usage_skips_non_coercible_int_fields() -> None:
    class UM:
        input_tokens = "not-an-int"
        output_tokens = 7
        total_tokens = None

    class Msg:
        usage_metadata = UM()

    class Resp:
        messages = [Msg()]

    assert _extract_token_usage(Resp()) == {"output_tokens": 7}


def test_extract_token_usage_dict_top_level_usage_metadata() -> None:
    """Dict-shaped responses may carry ``usage_metadata`` without ``messages``."""
    d = {"usage_metadata": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}}
    assert _extract_token_usage(d) == {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}


def test_extract_token_usage_sums_all_messages() -> None:
    class UM:
        def __init__(self, inp: int, out: int) -> None:
            self.input_tokens = inp
            self.output_tokens = out

    class Msg:
        def __init__(self, inp: int, out: int) -> None:
            self.usage_metadata = UM(inp, out)

    class Resp:
        messages = [Msg(10, 5), Msg(20, 8)]

    assert _extract_token_usage(Resp()) == {"input_tokens": 30, "output_tokens": 13}


def test_extend_invoke_config_merges_signal_queues_from_agent() -> None:
    import asyncio

    from agloom.worker import extend_invoke_config_with_event_queue

    eq = object()
    sq = asyncio.Queue()
    cqs: dict[str, asyncio.Queue] = {}
    agent: dict = {"signal_queue": sq, "clarification_queues": cqs, "_event_queue": eq}
    merged = extend_invoke_config_with_event_queue(None, eq, agent=agent)
    assert merged is not None
    assert merged["_event_queue"] is eq
    assert merged["configurable"]["signal_queue"] is sq
    assert merged["configurable"]["clarification_queues"] is cqs


def test_extend_invoke_config_keeps_existing_signal_queue() -> None:
    import asyncio

    from agloom.worker import extend_invoke_config_with_event_queue

    sq1 = asyncio.Queue()
    sq2 = asyncio.Queue()
    eq = object()
    agent = {"signal_queue": sq2, "clarification_queues": {}, "_event_queue": eq}
    inv = {"configurable": {"signal_queue": sq1, "thread_id": "t1"}}
    merged = extend_invoke_config_with_event_queue(inv, eq, agent=agent)
    assert merged is not None
    assert merged["configurable"]["signal_queue"] is sq1
    assert merged["configurable"]["thread_id"] == "t1"


@pytest.mark.asyncio
async def test_background_delegation_manager_shutdown_empty() -> None:
    m = BackgroundDelegationManager()
    await m.shutdown(cancel_pending=True)


def test_get_logger_dedupes_tracked_list() -> None:
    from agloom import logging_utils as lu

    name = f"agloom.tests.audit_hardening_dup_{uuid.uuid4().hex[:10]}"
    n_before = len(lu._tracked_loggers)
    get_logger(name)
    get_logger(name)
    assert len(lu._tracked_loggers) == n_before + 1
