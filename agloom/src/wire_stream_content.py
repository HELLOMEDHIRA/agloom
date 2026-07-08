"""Split provider stream chunks into model reasoning vs assistant answer text.

LangChain ``AIMessageChunk`` shapes differ by vendor (Anthropic thinking blocks,
DeepSeek ``reasoning_content``, OpenAI reasoning fields, Qwen inline
``<think>`` tags, …). All streaming paths should use
:func:`emit_llm_chunk_to_event_queue` so reasoning reaches AGP as
``token.delta`` with ``role="reasoning"`` and answer text as ``role="assistant"``.
"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import AIMessage

from .models import AgentEvent

_KWARGS_REASONING_KEYS = ("reasoning_content", "reasoning", "thinking")
_BLOCK_REASONING_TYPES = frozenset({"thinking", "reasoning", "reasoning_content"})
_SKIP_BLOCK_TYPES = frozenset({"image", "image_url", "input_audio", "video", "file"})

_QWEN_THINK_OPEN_RE = re.compile(r"<\s*(?:redacted_thinking|think)\s*>", re.IGNORECASE)
_QWEN_THINK_CLOSE_RE = re.compile(r"<\s*/\s*(?:redacted_thinking|think)\s*>", re.IGNORECASE)


def _surrogate_safe_text(text: str) -> str:
    if not text:
        return text
    return text.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")


def _split_qwen_inline_thinking(text: str) -> tuple[str, str]:
    """Return ``(reasoning, answer)`` from Qwen-style inline thinking tags in plain text."""
    if not text or not _QWEN_THINK_OPEN_RE.search(text):
        return "", text

    reasoning_parts: list[str] = []
    answer_parts: list[str] = []
    rest = text
    while True:
        open_match = _QWEN_THINK_OPEN_RE.search(rest)
        if not open_match:
            if rest:
                answer_parts.append(rest)
            break
        before = rest[: open_match.start()]
        if before:
            answer_parts.append(before)
        after_open = rest[open_match.end() :]
        close_match = _QWEN_THINK_CLOSE_RE.search(after_open)
        if close_match is None:
            if after_open:
                reasoning_parts.append(after_open)
            break
        think_body = after_open[: close_match.start()]
        if think_body:
            reasoning_parts.append(think_body)
        rest = after_open[close_match.end() :]

    return "".join(reasoning_parts), "".join(answer_parts)


def _text_from_mapping(block: dict[str, Any]) -> str:
    for key in ("thinking", "reasoning", "reasoning_content", "text", "content"):
        val = block.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _split_content_block(block: Any) -> tuple[str, str]:
    """Return ``(reasoning_piece, answer_piece)`` for one content block."""
    if isinstance(block, str):
        return _split_qwen_inline_thinking(block)
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
        return _split_qwen_inline_thinking(str(block.get("text", "")))
    if isinstance(block.get("text"), str):
        return _split_qwen_inline_thinking(block["text"])
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
            r, a = _split_qwen_inline_thinking(content)
            if r:
                reasoning_parts.append(r)
            if a:
                answer_parts.append(a)
    elif isinstance(content, list):
        for block in content:
            r, a = _split_content_block(block)
            if r:
                reasoning_parts.append(r)
            if a:
                answer_parts.append(a)
    elif content:
        r, a = _split_qwen_inline_thinking(str(content))
        if r:
            reasoning_parts.append(r)
        if a:
            answer_parts.append(a)

    return "".join(reasoning_parts), "".join(answer_parts)


def answer_text_from_content(content: Any) -> str:
    """Normalize final message content to assistant-visible answer text (no reasoning blocks)."""
    if content is None:
        return ""
    if isinstance(content, str):
        if _QWEN_THINK_OPEN_RE.search(content):
            _, answer = _split_qwen_inline_thinking(content)
            return answer
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            _, answer = _split_content_block(block)
            if answer:
                parts.append(answer)
        return "".join(parts)
    text = str(content)
    if _QWEN_THINK_OPEN_RE.search(text):
        _, answer = _split_qwen_inline_thinking(text)
        return answer
    return text


def sanitize_assistant_content_for_history(content: Any) -> Any:
    """Strip inline thinking from assistant content before it is stored in message history."""
    if isinstance(content, str):
        if not _QWEN_THINK_OPEN_RE.search(content):
            return content
        _, answer = _split_qwen_inline_thinking(content)
        return answer
    if isinstance(content, list):
        cleaned: list[Any] = []
        changed = False
        for block in content:
            if isinstance(block, str):
                new_block = sanitize_assistant_content_for_history(block)
                cleaned.append(new_block)
                changed = changed or new_block != block
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                new_text = sanitize_assistant_content_for_history(block["text"])
                if new_text != block["text"]:
                    updated = dict(block)
                    updated["text"] = new_text
                    cleaned.append(updated)
                    changed = True
                else:
                    cleaned.append(block)
            else:
                cleaned.append(block)
        return cleaned if changed else content
    return content


def sanitize_ai_message_for_history(msg: Any) -> Any:
    """Return a copy of an AI message with reasoning stripped from stored content."""
    content = getattr(msg, "content", None)
    if content is None:
        return msg
    clean = sanitize_assistant_content_for_history(content)
    if clean is content:
        return msg
    try:
        return msg.model_copy(update={"content": clean})  # type: ignore[attr-defined]
    except Exception:
        return msg


def sanitize_model_call_response(response: Any) -> Any:
    """Sanitize model-call responses so history never re-sends inline reasoning."""
    if isinstance(response, AIMessage):
        return sanitize_ai_message_for_history(response)
    content = getattr(response, "content", None)
    if content is not None:
        clean = sanitize_assistant_content_for_history(content)
        if clean is not content:
            try:
                return response.model_copy(update={"content": clean})  # type: ignore[attr-defined]
            except Exception:
                pass
    return response


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
