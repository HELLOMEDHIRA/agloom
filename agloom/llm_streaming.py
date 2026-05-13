"""Push ``llm.astream`` chunks to ``_event_queue`` for CLI/TUI live output."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage

from .models import AgentEvent


async def astream_llm_to_event_queue(
    llm: Any,
    messages: Sequence[BaseMessage],
    event_queue: Any,
    *,
    timeout: float,
    worker_id: str | None = None,
) -> tuple[str, Any | None]:
    """Stream model tokens as ``AgentEvent(type='token')``. Returns (full text, last chunk for usage)."""
    chunks: list[str] = []
    last_chunk: Any | None = None

    async def _consume() -> None:
        nonlocal last_chunk
        async for chunk in llm.astream(messages):
            last_chunk = chunk
            content = getattr(chunk, "content", "")
            if content:
                c = content if isinstance(content, str) else str(content)
                chunks.append(c)
                payload: dict[str, Any] = {"content": c}
                if worker_id:
                    payload["worker_id"] = worker_id
                await event_queue.put(AgentEvent(type="token", data=payload))

    await asyncio.wait_for(_consume(), timeout=timeout)
    return "".join(chunks), last_chunk


async def stream_or_invoke_llm(
    llm: Any,
    messages: Sequence[BaseMessage],
    agent: dict,
    *,
    timeout: float,
    worker_id: str | None = None,
) -> tuple[str, list[BaseMessage], Any | None]:
    """Stream tokens to ``agent['_event_queue']`` when set; else ``ainvoke``.

    Returns ``(text, message_tail_for_logging, usage_source)`` where *usage_source* is the
    last streamed chunk or the final ``AIMessage`` from ``ainvoke`` — suitable for
    :func:`_extract_token_usage` in pattern modules.
    """
    event_queue = agent.get("_event_queue")
    base: list[BaseMessage] = list(messages)
    if event_queue is not None:
        text, last_chunk = await astream_llm_to_event_queue(
            llm, messages, event_queue, timeout=timeout, worker_id=worker_id
        )
        tail = base.copy()
        if last_chunk is not None:
            tail.append(last_chunk)
        return text.strip(), tail, last_chunk
    resp = await asyncio.wait_for(llm.ainvoke(messages), timeout=timeout)
    tail = base + [resp]
    content = getattr(resp, "content", "")
    out = content if isinstance(content, str) else str(content)
    return out.strip(), tail, resp
