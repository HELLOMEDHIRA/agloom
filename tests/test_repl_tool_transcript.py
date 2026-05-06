"""Transcript merge: tool results (e.g. read_file) appended when the model only summarizes."""

from agloom_cli.repl import append_tool_result_for_transcript, merge_transcript_with_tool_outputs


def test_merge_appends_read_file_block() -> None:
    accum: list[tuple[str, str]] = []
    append_tool_result_for_transcript("read_file", "1|a\n2|b", accum)
    out = merge_transcript_with_tool_outputs("Here is a summary.", accum)
    assert "Here is a summary." in out
    assert "--- tool output ---" in out
    assert "read_file:" in out
    assert "1|a" in out


def test_append_skips_errors_and_unknown_tools() -> None:
    accum: list[tuple[str, str]] = []
    append_tool_result_for_transcript("read_file", "Error: not found", accum)
    append_tool_result_for_transcript("unknown_tool", "x", accum)
    assert accum == []


def test_merge_empty_stream_uses_tools_only() -> None:
    accum: list[tuple[str, str]] = [("read_file", "only")]
    assert merge_transcript_with_tool_outputs("", accum) == "read_file:\nonly"
