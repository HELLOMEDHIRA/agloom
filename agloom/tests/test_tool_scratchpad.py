"""Tests for tool scratchpad, compaction, and context window helpers."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, ToolMessage

from agloom.context.compaction import compact_messages_for_budget
from agloom.context.errors import ContextBudgetExceededError
from agloom.context.tool_scratchpad import (
    MAX_TOOL_WIRE_CHARS,
    ToolScratchpad,
    build_tool_digest,
    extract_ref_id_from_digest,
    is_monolithic_payload,
    make_recall_tool_artifact,
)
from agloom.context.window import infer_context_window_tokens, reserved_output_tokens
from agloom.patterns.react_tool_recovery import exception_indicates_context_window_exceeded
from agloom.patterns.tool_context_middleware import tool_context_settings_from_mapping


class _FakeLLM:
    max_tokens = 32_768
    model_name = "qwen/qwen3-32b"


def test_build_tool_digest_and_recall_slices():
    pad = ToolScratchpad()
    body = "line\n" * 40
    art = pad.store("grep_logs", body)
    digest = build_tool_digest(ref_id=art.ref_id, tool_name="grep_logs", full_text=body)
    assert "[agloom:tool_digest" in digest
    ref = extract_ref_id_from_digest(digest)
    assert ref == art.ref_id

    recall = make_recall_tool_artifact(pad)
    full = recall.invoke({"ref_id": art.ref_id})
    assert "grep_logs" in full
    assert "line" in full

    page = recall.invoke({"ref_id": art.ref_id, "offset": 0, "limit": 10})
    assert "offset=10" in page or "slice=0:10" in page


def test_compact_messages_replaces_old_tool_outputs():
    pad = ToolScratchpad()
    big = "x" * 8000
    msgs = [
        HumanMessage(content="investigate"),
        ToolMessage(content=big, tool_call_id="tc1", name="fetch"),
        ToolMessage(content="small ok", tool_call_id="tc2", name="status"),
        ToolMessage(content=big, tool_call_id="tc3", name="fetch"),
    ]
    compacted = compact_messages_for_budget(msgs, pad, target_input_tokens=500, keep_recent_tool_rounds=2)
    assert "[compacted tool=" in str(compacted[1].content)
    assert compacted[2].content == "small ok"
    assert "[agloom:tool_digest" in str(compacted[3].content) or "[compacted tool=" in str(
        compacted[3].content
    )


def test_context_window_inference_and_output_cap():
    window = infer_context_window_tokens(_FakeLLM(), "qwen3-32b-131k")
    assert window >= 131_072
    reserved = reserved_output_tokens(_FakeLLM(), context_window=window)
    assert reserved <= 8192
    assert reserved < 32_768


def test_exception_indicates_context_window():
    err = RuntimeError("ContextWindowExceededError: reduce the length of the input prompt")
    assert exception_indicates_context_window_exceeded(err)


def test_tool_context_settings_from_mapping():
    pad = ToolScratchpad()
    cfg = {
        "_tool_scratchpad": pad,
        "context_window_tokens": 131072,
        "context_reserved_output_tokens": 4096,
        "tool_digest_min_chars": 2000,
    }
    settings = tool_context_settings_from_mapping(cfg)
    assert settings is not None
    assert settings["scratchpad"] is pad
    assert settings["context_window"] == 131072
    assert settings["digest_min_chars"] == 2000

    assert tool_context_settings_from_mapping({"tool_scratchpad": False, "_tool_scratchpad": pad}) is not None


def test_monolithic_json_digest_metadata_only():
    pad = ToolScratchpad()
    body = '{"events":[' + '{"id":1},' * 5000 + '{"id":9999}]}'
    assert is_monolithic_payload(body)
    art = pad.store("obs_logs", body)
    digest = build_tool_digest(ref_id=art.ref_id, tool_name="obs_logs", full_text=body)
    assert body not in digest
    assert "format=json" in digest
    assert len(digest) < len(body)
    assert len(digest) <= MAX_TOOL_WIRE_CHARS


def test_multiline_log_preview_bounded():
    pad = ToolScratchpad()
    body = "\n".join(f"log line {i}" for i in range(40))
    art = pad.store("grep_logs", body)
    digest = build_tool_digest(ref_id=art.ref_id, tool_name="grep_logs", full_text=body)
    assert "--- preview ---" in digest
    assert "log line 0" in digest
    assert "log line 39" not in digest
    assert len(digest) <= MAX_TOOL_WIRE_CHARS


def test_oversized_recent_tool_digested_on_size_pass():
    pad = ToolScratchpad()
    big = "y" * (MAX_TOOL_WIRE_CHARS + 5000)
    msgs = [
        HumanMessage(content="q"),
        ToolMessage(content=big, tool_call_id="tc1", name="fetch"),
        ToolMessage(content=big, tool_call_id="tc2", name="fetch"),
    ]
    compacted = compact_messages_for_budget(
        msgs,
        pad,
        target_input_tokens=10_000_000,
        keep_recent_tool_rounds=2,
        max_wire_chars=MAX_TOOL_WIRE_CHARS,
    )
    for msg in compacted:
        if isinstance(msg, ToolMessage):
            assert len(str(msg.content)) <= MAX_TOOL_WIRE_CHARS


def test_context_budget_exceeded_error_fields():
    err = ContextBudgetExceededError(estimated_tokens=99_000, budget=50_000)
    assert err.estimated_tokens == 99_000
    assert err.budget == 50_000
    assert "Context budget exceeded" in str(err)

