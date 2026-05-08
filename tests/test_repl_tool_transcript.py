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


def test_merge_list_directory_when_stream_nonempty_skips_duplicate_block() -> None:
    accum: list[tuple[str, str]] = []
    append_tool_result_for_transcript("list_directory", "hello.txt (17.0 B)", accum)
    out = merge_transcript_with_tool_outputs(
        "List of files in _agloom_tool_smoke: hello.txt (17.0 B)", accum
    )
    assert out == "List of files in _agloom_tool_smoke: hello.txt (17.0 B)"
    assert "--- tool output ---" not in out


def test_merge_list_directory_when_stream_empty_still_shows_tool() -> None:
    accum: list[tuple[str, str]] = []
    append_tool_result_for_transcript("list_directory", "hello.txt (17.0 B)", accum)
    assert merge_transcript_with_tool_outputs("", accum) == "list_directory:\nhello.txt (17.0 B)"


def test_merge_nonempty_stream_keeps_read_file_block() -> None:
    accum: list[tuple[str, str]] = []
    append_tool_result_for_transcript("list_directory", "a.txt", accum)
    append_tool_result_for_transcript("read_file", "1|line", accum)
    out = merge_transcript_with_tool_outputs("Listed dir and read file.", accum)
    assert "Listed dir and read file." in out
    assert "read_file:" in out
    assert "1|line" in out
    assert "list_directory:" not in out
