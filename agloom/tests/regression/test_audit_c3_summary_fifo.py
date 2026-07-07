"""C3: summary turns must not be dropped by FIFO trim."""

from langgraph.store.memory import InMemoryStore

from agloom.memory.session import SessionMemory, _SUMMARY_MARKER


def test_trim_preserves_summary_turns():
    from agloom.memory.session import _trim_turns_preserving_summaries

    turns = [{"q": _SUMMARY_MARKER, "a": "summary", "p": "summary"}]
    turns += [{"q": f"q{i}", "a": f"a{i}", "p": ""} for i in range(10)]
    out = _trim_turns_preserving_summaries(turns, max_turns=5)
    assert any(t.get("q") == _SUMMARY_MARKER for t in out)
