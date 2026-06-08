"""Translator cross-thread filtering and tool call ids."""

from __future__ import annotations

import io
import json

from agloom.models import AgentEvent
from agloom.protocol import SessionEmitter, event_adapter
from agloom.runtime.translator import translate


def _events(buf: io.StringIO) -> list:
    buf.seek(0)
    return [event_adapter.validate_python(json.loads(line)) for line in buf if line.strip()]


def test_translate_drops_foreign_thread_events() -> None:
    buf = io.StringIO()
    em = SessionEmitter(session="s", thread="thread_a", writer=buf)
    em.open()
    translate(AgentEvent(type="token", data={"content": "x", "thread_id": "thread_b"}), em)
    types = [e.type for e in _events(buf)]
    assert "stream.token.delta" not in types


def test_translate_uses_unique_tool_call_ids() -> None:
    buf = io.StringIO()
    em = SessionEmitter(session="s", thread="t", writer=buf)
    em.open()
    translate(AgentEvent(type="tool_call", data={"name": "read_file", "args": {}}), em)
    translate(AgentEvent(type="tool_call", data={"name": "read_file", "args": {}}), em)
    ids = [e.data.tool_call_id for e in _events(buf) if e.type == "tool.call.start"]
    assert len(ids) == 2
    assert ids[0] != ids[1]
