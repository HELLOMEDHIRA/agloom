"""Unmapped AgentEvent types with output surface as full ``thinking.step`` detail."""

from __future__ import annotations

from unittest.mock import MagicMock

from agloom.models import AgentEvent
from agloom.runtime.translator import translate


def test_unmapped_event_skipped_when_no_output_and_not_verbose(monkeypatch) -> None:
    monkeypatch.delenv("AGLOOM_TRANSLATOR_VERBOSE_THINKING", raising=False)
    import agloom.runtime.translator as tr

    monkeypatch.setattr(tr, "_TRANSLATOR_VERBOSE_THINKING", False)
    emitter = MagicMock()
    emitter._thread = "t1"
    translate(AgentEvent(type="internal.debug", data={}), emitter)
    emitter.emit_thinking_step.assert_not_called()


def test_unmapped_event_emits_full_output(monkeypatch) -> None:
    import agloom.runtime.translator as tr

    monkeypatch.setattr(tr, "_TRANSLATOR_VERBOSE_THINKING", False)
    emitter = MagicMock()
    emitter._thread = "t1"
    long_out = "x" * 500
    translate(AgentEvent(type="internal.debug", data={"output": long_out}), emitter)
    emitter.emit_thinking_step.assert_called_once()
    detail = emitter.emit_thinking_step.call_args.kwargs.get("detail") or ""
    assert detail == long_out
