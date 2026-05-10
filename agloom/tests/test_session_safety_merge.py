"""Tests for concurrent session safety and emitter fork/merge correctness.

Exercises:
- Monotonic seq across concurrent forks (the _SharedSeq guarantee).
- Concurrent emit from multiple threads doesn't produce duplicate seq numbers.
- fork_for_thread emits on the correct thread field.
- Multiple forks of the same session share a single seq counter.
"""

from __future__ import annotations

import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from agloom.protocol.emitter import SessionEmitter, _SharedSeq

# ── _SharedSeq ───────────────────────────────────────────────────────────────


def test_shared_seq_monotonic() -> None:
    seq = _SharedSeq()
    values = [seq.next() for _ in range(100)]
    assert values == list(range(1, 101))


def test_shared_seq_thread_safe_no_duplicates() -> None:
    """All seq values produced by N threads must be unique and contiguous."""
    seq = _SharedSeq()
    N, PER_THREAD = 8, 200
    results: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(PER_THREAD):
            v = seq.next()
            with lock:
                results.append(v)

    with ThreadPoolExecutor(max_workers=N) as pool:
        futures = [pool.submit(worker) for _ in range(N)]
        for f in futures:
            f.result()

    assert len(results) == N * PER_THREAD
    assert sorted(results) == list(range(1, N * PER_THREAD + 1)), "duplicate or missing seq values"


# ── SessionEmitter ────────────────────────────────────────────────────────────


def _make_emitter(buf: io.StringIO, session: str = "s_test", thread: str = "t_main") -> SessionEmitter:
    return SessionEmitter(session=session, thread=thread, writer=buf)


def _parse_events(buf: io.StringIO) -> list[dict]:
    buf.seek(0)
    return [json.loads(line) for line in buf if line.strip()]


def test_emitter_seq_monotonic_single_thread() -> None:
    buf = io.StringIO()
    emitter = _make_emitter(buf)
    emitter.open()
    for _ in range(5):
        emitter.emit_thinking_step(step="test", label="t")
    emitter.close()

    events = _parse_events(buf)
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs), "seq not monotonically increasing"
    assert seqs == list(range(1, len(seqs) + 1)), "seq not contiguous starting at 1"


def test_fork_uses_correct_thread() -> None:
    buf = io.StringIO()
    emitter = _make_emitter(buf, thread="t_main")
    emitter.open()

    fork = emitter.fork_for_thread("t_worker")
    fork.emit_thinking_step(step="worker_step", label="w")
    emitter.emit_thinking_step(step="main_step", label="m")
    emitter.close()

    events = _parse_events(buf)
    threads = {e["thread"] for e in events if e.get("type") == "thinking.step"}
    assert "t_worker" in threads
    assert "t_main" in threads


def test_fork_shares_seq_counter() -> None:
    """Fork and parent must produce non-duplicate, monotonically increasing seq."""
    buf = io.StringIO()
    emitter = _make_emitter(buf, thread="t_main")
    emitter.open()

    fork = emitter.fork_for_thread("t_fork")
    for _ in range(3):
        emitter.emit_thinking_step(step="p", label="parent")
        fork.emit_thinking_step(step="f", label="fork")
    emitter.close()

    events = _parse_events(buf)
    seqs = [e["seq"] for e in events]
    assert sorted(seqs) == list(range(1, len(seqs) + 1)), "seq collision between parent and fork"


def test_concurrent_emit_no_duplicate_seq() -> None:
    """Two forks emitting from separate threads must not produce duplicate seq values."""
    buf = io.StringIO()
    lock = threading.Lock()

    class _ThreadSafeIO:
        def write(self, s: str) -> None:
            with lock:
                buf.write(s)

        def flush(self) -> None:
            pass

    safe_buf = _ThreadSafeIO()
    emitter = SessionEmitter(session="s_concurrent", thread="t_main", writer=safe_buf)  # type: ignore[arg-type]
    emitter.open()
    fork_a = emitter.fork_for_thread("t_a")
    fork_b = emitter.fork_for_thread("t_b")

    ITERS = 50

    def emit_a() -> None:
        for i in range(ITERS):
            fork_a.emit_thinking_step(step=f"a_{i}", label="a")

    def emit_b() -> None:
        for i in range(ITERS):
            fork_b.emit_thinking_step(step=f"b_{i}", label="b")

    ta = threading.Thread(target=emit_a)
    tb = threading.Thread(target=emit_b)
    ta.start()
    tb.start()
    ta.join()
    tb.join()
    emitter.close()

    events = _parse_events(buf)
    thinking = [e for e in events if e.get("type") == "thinking.step"]
    seqs = [e["seq"] for e in thinking]
    assert len(seqs) == len(set(seqs)), "duplicate seq values emitted by concurrent forks"


def test_open_close_reason_preserved() -> None:
    buf = io.StringIO()
    emitter = _make_emitter(buf)
    emitter.open()
    emitter.close(reason="user_aborted")

    events = _parse_events(buf)
    close_evt = next(e for e in events if e.get("type") == "session.closed")
    assert close_evt["data"]["reason"] == "user_aborted"


def test_emit_token_delta_text_preserved() -> None:
    buf = io.StringIO()
    emitter = _make_emitter(buf)
    emitter.open()
    emitter.emit_token_delta(text=" hello world ", role="assistant")
    emitter.close()

    events = _parse_events(buf)
    delta = next(e for e in events if e.get("type") == "token.delta")
    assert delta["data"]["text"] == " hello world ", "leading/trailing whitespace must be preserved"
