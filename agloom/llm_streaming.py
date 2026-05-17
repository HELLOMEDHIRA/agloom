"""Push ``llm.astream`` chunks to ``_event_queue`` for CLI/TUI live output."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage

from .logging_utils import get_logger
from .models import AgentEvent

logger = get_logger(__name__)


async def astream_llm_to_event_queue(
    llm: Any,
    messages: Sequence[BaseMessage],
    event_queue: Any,
    *,
    timeout: float,
    worker_id: str | None = None,
) -> tuple[str, Any | None, dict[str, int]]:
    """Stream model tokens as ``AgentEvent(type='token')``.

    Returns ``(full text, last chunk, merged_usage_from_chunks)``. *merged_usage* combines
    ``usage_metadata`` from all chunks (cumulative / partial provider semantics).

    On timeout or cancellation, the async stream is closed via ``aclose()`` so provider
    connections are not left open under load.
    """
    chunks: list[str] = []
    last_chunk: Any | None = None
    usage_merged: dict[str, int] = {}

    agen = llm.astream(messages)
    try:
        async with asyncio.timeout(timeout):
            from .wire_tokens import accumulate_stream_usage

            async for chunk in agen:
                last_chunk = chunk
                accumulate_stream_usage(usage_merged, chunk)
                content = getattr(chunk, "content", "")
                if content:
                    c = content if isinstance(content, str) else str(content)
                    chunks.append(c)
                    payload: dict[str, Any] = {"content": c}
                    if worker_id:
                        payload["worker_id"] = worker_id
                    await event_queue.put(AgentEvent(type="token", data=payload))
    finally:
        aclose = getattr(agen, "aclose", None)
        if aclose is not None and inspect.iscoroutinefunction(aclose):
            with contextlib.suppress(Exception):
                await aclose()

    return "".join(chunks), last_chunk, usage_merged


async def stream_or_invoke_llm(
    llm: Any,
    messages: Sequence[BaseMessage],
    agent: dict,
    *,
    timeout: float,
    worker_id: str | None = None,
    phase: str | None = None,
) -> tuple[str, list[BaseMessage], Any | None]:
    """Stream tokens to ``agent['_event_queue']`` when set; else ``ainvoke``.

    Returns ``(text, message_tail_for_logging, usage_source)`` where *usage_source* is the
    last streamed chunk or the final ``AIMessage`` from ``ainvoke``. Streaming paths merge
    per-chunk ``usage_metadata`` before emission (see :func:`~agloom.wire_tokens.accumulate_stream_usage`).
    """
    event_queue = agent.get("_event_queue")
    base: list[BaseMessage] = list(messages)
    if event_queue is not None:
        text, last_chunk, stream_usage = await astream_llm_to_event_queue(
            llm, messages, event_queue, timeout=timeout, worker_id=worker_id
        )
        from .wire_tokens import emit_usage_from_llm_response, llm_label_from_run_config

        await emit_usage_from_llm_response(
            agent,
            last_chunk,
            phase=phase or (worker_id or "llm"),
            model=llm_label_from_run_config(agent),
            stream_accumulated=stream_usage,
        )
        tail = base.copy()
        if last_chunk is not None:
            tail.append(last_chunk)
        return text.strip(), tail, last_chunk
    resp = await asyncio.wait_for(llm.ainvoke(messages), timeout=timeout)
    from .wire_tokens import emit_usage_from_llm_response, llm_label_from_run_config

    await emit_usage_from_llm_response(
        agent,
        resp,
        phase=phase or (worker_id or "llm"),
        model=llm_label_from_run_config(agent),
    )
    tail = base + [resp]
    content = getattr(resp, "content", "")
    out = content if isinstance(content, str) else str(content)
    return out.strip(), tail, resp
