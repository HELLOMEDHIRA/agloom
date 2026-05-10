"""Subprocess integration test for the AGP stdio transport.

Starts a minimal Python process that emulates the agloom runtime's NDJSON output
and verifies that the full stdio round-trip (NDJSON → Envelope parsing) works
end-to-end without requiring an actual LLM API key.

The test spawns a child process that writes a fixed sequence of AGP events to
stdout, then reads them back and validates the parsed envelope shapes.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest

from agloom.protocol import event_adapter
from agloom.protocol.events import MessageAssistant, SessionClosed, SessionOpened, TokenDelta

FAKE_RUNTIME_SCRIPT = textwrap.dedent("""\
    import json, sys, time
    from uuid import uuid4

    SESSION = "s_integration_test"
    THREAD  = "t_main"

    def evt(type_, seq, data):
        return {
            "v": "1",
            "type": type_,
            "id": uuid4().hex,
            "session": SESSION,
            "thread": THREAD,
            "seq": seq,
            "ts": "2026-01-01T00:00:00Z",
            "data": data,
        }

    events = [
        evt("session.opened", 1, {
            "runtime_version": "0.1.0",
            "protocol_version": "1",
            "capabilities": ["agp.v1.minimal"],
        }),
        evt("message.user", 2, {"content": "hello world"}),
        evt("token.delta", 3, {"text": "Hi ", "role": "assistant"}),
        evt("token.delta", 4, {"text": "there!", "role": "assistant"}),
        evt("message.assistant", 5, {"content": "Hi there!", "message_id": None, "pattern": None}),
        evt("session.closed", 6, {"reason": "completed", "duration_ms": 42}),
    ]

    for e in events:
        sys.stdout.write(json.dumps(e) + "\\n")
        sys.stdout.flush()
""")


@pytest.mark.asyncio
async def test_stdio_transport_round_trip() -> None:
    """Start a subprocess that emits 6 AGP events; parse all via event_adapter."""
    result = subprocess.run(
        [sys.executable, "-c", FAKE_RUNTIME_SCRIPT],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, f"script failed:\n{result.stderr}"

    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 6, f"expected 6 NDJSON lines, got {len(lines)}"

    parsed = [event_adapter.validate_python(json.loads(ln)) for ln in lines]

    types = [p.type for p in parsed]
    assert types == [
        "session.opened",
        "message.user",
        "token.delta",
        "token.delta",
        "message.assistant",
        "session.closed",
    ]

    # Structural spot-checks (narrow union members for the type checker)
    opened = parsed[0]
    assert isinstance(opened, SessionOpened)
    assert opened.data.runtime_version == "0.1.0"
    assert "agp.v1.minimal" in opened.data.capabilities

    token1 = parsed[2]
    assert isinstance(token1, TokenDelta)
    assert token1.data.text == "Hi "
    assert token1.data.role == "assistant"

    assert isinstance(parsed[4], MessageAssistant)

    closed = parsed[5]
    assert isinstance(closed, SessionClosed)
    assert closed.data.reason == "completed"
    assert closed.data.duration_ms == 42

    # All events share the same session id and have monotonically increasing seq
    sessions = {p.session for p in parsed}
    assert sessions == {"s_integration_test"}

    seqs = [p.seq for p in parsed]
    assert seqs == sorted(seqs)
    assert seqs == list(range(1, 7))
