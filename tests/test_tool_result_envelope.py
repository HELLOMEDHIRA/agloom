"""Structured incomplete tool results."""

from agloom_cli.tool_result_envelope import render_complete, render_incomplete


def test_render_complete_passthrough() -> None:
    assert render_complete("ok") == "ok"


def test_render_incomplete_contains_meta_and_preview() -> None:
    s = render_incomplete(
        kind="test_kind",
        metrics={"n": 42},
        hints=["do something"],
        preview="hello",
    )
    assert "[agloom:tool_result]" in s
    assert "complete=false" in s
    assert "kind=test_kind" in s
    assert "n=42" in s
    assert "[/agloom:tool_result]" in s
    assert "Recovery:" in s
    assert "- do something" in s
    assert "hello" in s
