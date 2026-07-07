"""Tool catalog emission and envelope trace wiring."""

from io import StringIO

from agloom.protocol.emitter import SessionEmitter
from agloom.runtime.session_bootstrap import emit_agent_tool_catalog


class _FakeTool:
    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description


def test_emit_agent_tool_catalog_runtime_tools():
    buf = StringIO()
    emitter = SessionEmitter(session="s1", thread="t1", writer=buf)
    emitter.open()
    agent = {"config": {"tools": [_FakeTool("search", "search the web")], "llm": None, "name": "A"}}
    emit_agent_tool_catalog(emitter, agent)
    blob = buf.getvalue()
    assert "runtime.tools" in blob or "runtime.config" in blob


def test_envelope_trace_set_on_open():
    emitter = SessionEmitter(session="s1", thread="t1", writer=None)
    evt = emitter.open()
    assert evt.trace is not None
    assert evt.trace.startswith("tr_")
