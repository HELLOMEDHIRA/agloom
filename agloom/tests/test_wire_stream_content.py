"""Model-native reasoning extraction from streamed LLM chunks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agloom.multimodal import content_blocks_to_text
from agloom.wire_stream_content import (
    answer_text_from_content,
    emit_llm_chunk_to_event_queue,
    split_stream_parts_from_chunk,
)


def test_split_anthropic_thinking_and_text_blocks() -> None:
    chunk = SimpleNamespace(
        content=[
            {"type": "thinking", "thinking": "Let me check the file."},
            {"type": "text", "text": "Here is the answer."},
        ],
        additional_kwargs={},
    )
    reasoning, answer = split_stream_parts_from_chunk(chunk)
    assert "check the file" in reasoning
    assert answer == "Here is the answer."


def test_split_deepseek_reasoning_content_kwargs() -> None:
    chunk = SimpleNamespace(
        content="Final answer.",
        additional_kwargs={"reasoning_content": "Step one. Step two."},
    )
    reasoning, answer = split_stream_parts_from_chunk(chunk)
    assert reasoning == "Step one. Step two."
    assert answer == "Final answer."


def test_answer_text_excludes_thinking_blocks() -> None:
    content = [
        {"type": "thinking", "thinking": "hidden"},
        {"type": "text", "text": "visible"},
    ]
    assert answer_text_from_content(content) == "visible"
    assert content_blocks_to_text(content) == "visible"


def test_redacted_thinking_surfaces_placeholder() -> None:
    chunk = SimpleNamespace(
        content=[{"type": "redacted_thinking"}],
        additional_kwargs={},
    )
    reasoning, answer = split_stream_parts_from_chunk(chunk)
    assert reasoning == "[redacted thinking]"
    assert answer == ""


@pytest.mark.asyncio
async def test_emit_llm_chunk_splits_roles_on_queue() -> None:
    import asyncio

    q: asyncio.Queue = asyncio.Queue()
    chunk = SimpleNamespace(
        content=[{"type": "text", "text": "Hi"}],
        additional_kwargs={"reasoning_content": "Hmm"},
    )
    await emit_llm_chunk_to_event_queue(q, chunk)
    first = await q.get()
    second = await q.get()
    assert first.type == "token"
    assert first.data["role"] == "reasoning"
    assert first.data["content"] == "Hmm"
    assert second.data["role"] == "assistant"
    assert second.data["content"] == "Hi"
