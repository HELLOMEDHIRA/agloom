"""Push ``llm.astream`` chunks to ``_event_queue`` for CLI/TUI live output."""

from __future__ import annotations

import asyncio
from typing import Any, Sequence

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
