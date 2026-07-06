"""Split provider stream chunks into model reasoning vs assistant answer text.

LangChain ``AIMessageChunk`` shapes differ by vendor (Anthropic thinking blocks,
DeepSeek ``reasoning_content``, OpenAI reasoning fields, …). All streaming paths
should use :func:`emit_llm_chunk_to_event_queue` so reasoning reaches AGP as
``token.delta`` with ``role="reasoning"`` and answer text as ``role="assistant"``.
"""

from __future__ import annotations

from typing import Any

from .models import AgentEvent

_KWARGS_REASONING_KEYS = ("reasoning_content", "reasoning", "thinking")
_BLOCK_REASONING_TYPES = frozenset({"thinking", "reasoning", "reasoning_content"})
_SKIP_BLOCK_TYPES = frozenset({"image", "image_url", "input_audio", "video", "file"})


def _surrogate_safe_text(text: str) -> str:
    if not text:
        return text
    return text.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")


def _text_from_mapping(block: dict[str, Any]) -> str:
    for key in ("thinking", "reasoning", "reasoning_content", "text", "content"):
        val = block.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _split_content_block(block: Any) -> tuple[str, str]:
    """Return ``(reasoning_piece, answer_piece)`` for one content block."""
    if isinstance(block, str):
        return "", block
    if not isinstance(block, dict):
        return "", str(block)
    btype = block.get("type")
    if btype in _BLOCK_REASONING_TYPES:
        return _text_from_mapping(block), ""
    if btype == "redacted_thinking":
        return "[redacted thinking]", ""
    if btype in _SKIP_BLOCK_TYPES:
        return "", ""
    if btype == "text":
        return "", str(block.get("text", ""))
    if isinstance(block.get("text"), str):
        return "", block["text"]
    return "", ""


def _kwargs_reasoning_delta(chunk: Any) -> str:
    kwargs = getattr(chunk, "additional_kwargs", None)
    if not isinstance(kwargs, dict):
        return ""
    parts: list[str] = []
    for key in _KWARGS_REASONING_KEYS:
        val = kwargs.get(key)
        if isinstance(val, str) and val:
            parts.append(val)
    meta = getattr(chunk, "response_metadata", None)
    if isinstance(meta, dict):
        for key in _KWARGS_REASONING_KEYS:
            val = meta.get(key)
            if isinstance(val, str) and val:
                parts.append(val)
    for attr in _KWARGS_REASONING_KEYS:
        val = getattr(chunk, attr, None)
        if isinstance(val, str) and val:
            parts.append(val)
    return "".join(parts)


def split_stream_parts_from_chunk(chunk: Any) -> tuple[str, str]:
    """Return ``(reasoning_delta, answer_delta)`` from one streamed LLM chunk."""
    reasoning_parts: list[str] = []
    answer_parts: list[str] = []

    kw = _kwargs_reasoning_delta(chunk)
    if kw:
        reasoning_parts.append(kw)

    content = getattr(chunk, "content", None)
    if content is None:
        return "".join(reasoning_parts), "".join(answer_parts)
    if isinstance(content, str):
        if content:
            answer_parts.append(content)
    elif isinstance(content, list):
        for block in content:
            r, a = _split_content_block(block)
            if r:
                reasoning_parts.append(r)
            if a:
                answer_parts.append(a)
    elif content:
        answer_parts.append(str(content))

    return "".join(reasoning_parts), "".join(answer_parts)


def answer_text_from_content(content: Any) -> str:
    """Normalize final message content to assistant-visible answer text (no reasoning blocks)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            _, answer = _split_content_block(block)
            if answer:
                parts.append(answer)
        return "".join(parts)
    return str(content)


async def emit_llm_chunk_to_event_queue(
    queue: Any,
    chunk: Any,
    *,
    worker_id: str | None = None,
) -> tuple[str, str]:
    """Push reasoning/answer deltas from *chunk* onto *queue*."""
    reasoning, answer = split_stream_parts_from_chunk(chunk)
    if reasoning:
        payload: dict[str, Any] = {
            "content": _surrogate_safe_text(reasoning),
            "role": "reasoning",
        }
        if worker_id:
            payload["worker_id"] = worker_id
        await queue.put(AgentEvent(type="token", data=payload))
    if answer:
        payload = {"content": _surrogate_safe_text(answer), "role": "assistant"}
        if worker_id:
            payload["worker_id"] = worker_id
        await queue.put(AgentEvent(type="token", data=payload))
    return reasoning, answer
