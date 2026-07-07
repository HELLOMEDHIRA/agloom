"""Short-term conversation memory scoped to a thread_id with auto-summarization."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ..src.logging_utils import get_logger

logger = get_logger(__name__)

_NAMESPACE_PREFIX = ("session",)

_SUMMARY_MARKER = "[SUMMARY]"

from ..context.summarize import summarize_oldest_turns, summarize_oldest_turns_sync

_CHARS_PER_TOKEN = 4
_tiktoken_encoder: Any | None = None
_tiktoken_encoder_lock = threading.Lock()


def _get_tiktoken_encoder() -> Any | None:
    global _tiktoken_encoder
    if _tiktoken_encoder is not None:
        return _tiktoken_encoder
    with _tiktoken_encoder_lock:
        if _tiktoken_encoder is not None:
            return _tiktoken_encoder
        try:
            import tiktoken

            _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _tiktoken_encoder = None
    return _tiktoken_encoder


def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken if available, else char approximation."""
    enc = _get_tiktoken_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    return len(text) // _CHARS_PER_TOKEN


def _turns_to_text(turns: list[dict]) -> str:
    lines: list[str] = []
    for t in turns:
        q = t.get("q", "")
        a = t.get("a", "")
        if q == _SUMMARY_MARKER:
            lines.append(f"[Previous summary]: {a}")
        else:
            lines.append(f"User: {q}")
            lines.append(f"Assistant: {a}")
    return "\n".join(lines)


def _total_tokens(turns: list[dict]) -> int:
    return _count_tokens(_turns_to_text(turns))


def _trim_turns_preserving_summaries(turns: list[dict], max_turns: int) -> list[dict]:
    """Drop oldest non-summary turns first; never discard summary turns."""
    if len(turns) <= max_turns:
        return turns
    summaries = [t for t in turns if t.get("q") == _SUMMARY_MARKER or t.get("p") == "summary"]
    non_summary = [t for t in turns if t not in summaries]
    keep_non = max(0, max_turns - len(summaries))
    trimmed = non_summary[-keep_non:] if keep_non else []
    return summaries + trimmed


class SessionMemory:
    """
    Short-term memory scoped to a thread_id.
    Each thread -> one key in the store, value = {turns: [...]}

    Each turn stores full ``q`` / ``a`` text as provided. Prompt injection via
    :func:`~agloom.memory.build_memory_context` may still cap rendered size with ``max_chars``.

    Auto-summarization (always on when summarizer_model is set):
      When accumulated tokens exceed ~80% of summarize_max_tokens_budget (inferred from
      model window when unset), oldest turns are compressed via the Context Plane episodic
      summarizer. Summary turns are preserved across max_turns trimming.
    """

    def __init__(
        self,
        store: Any = None,
        max_turns: int = 50,
        summarizer_model: Any = None,
        *,
        summarize_max_tokens_budget: int | None = None,
        on_turns_async: Callable[[str, list[dict[str, Any]]], Awaitable[None]] | None = None,
        agp_session_key: str | None = None,
        on_episodic_summary: Callable[[str, Any], Awaitable[None] | None] | None = None,
    ) -> None:
        if store is None:
            from langgraph.store.memory import InMemoryStore

            store = InMemoryStore()
            logger.debug(
                "SessionMemory auto-created with ephemeral InMemoryStore. "
                "Pass memory=SessionMemory(store=AsyncSqliteStore(...)) for persistence."
            )
        self.store = store
        self.max_turns = max_turns
        self.summarizer_model = summarizer_model
        self.summarize_max_tokens_budget = summarize_max_tokens_budget
        self.on_turns_async = on_turns_async
        self.on_episodic_summary = on_episodic_summary
        self.agp_session_key = (agp_session_key or "").strip() or None
        self._turn_lock = asyncio.Lock()
        self._sync_turn_lock = threading.Lock()

    async def _notify_turns_hook(self, thread_id: str, turns: list[dict]) -> None:
        cb = self.on_turns_async
        if cb is None:
            return
        try:
            await cb(thread_id, turns)
        except Exception as exc:
            logger.debug(f"SessionMemory on_turns_async failed (non-fatal): {exc!r}")

    def _ns(self, thread_id: str) -> tuple:
        if self.agp_session_key:
            return _NAMESPACE_PREFIX + (self.agp_session_key, thread_id)
        return _NAMESPACE_PREFIX + (thread_id,)

    def _effective_summarize_token_threshold(self) -> int:
        """Estimated-token ceiling before compressing oldest turns."""
        if self.summarize_max_tokens_budget is not None:
            b = self.summarize_max_tokens_budget
            if b > 0:
                return max(1, int(b * 0.8))
        return 200_000

    async def _persist_episodic_summary(self, thread_id: str, episodic: Any) -> None:
        cb = self.on_episodic_summary
        if cb is None:
            return
        try:
            result = cb(thread_id, episodic)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.debug(f"SessionMemory on_episodic_summary failed (non-fatal): {exc!r}")

    def _maybe_summarize_sync(self, turns: list[dict]) -> list[dict]:
        """Sync summarize for ``add_turn`` (uses ``invoke`` when a model is configured)."""
        if self.summarizer_model is None or len(turns) < 4:
            return turns

        total = _total_tokens(turns)
        if total <= self._effective_summarize_token_threshold():
            return turns

        compressed, _ = summarize_oldest_turns_sync(
            turns,
            summarizer_model=self.summarizer_model,
        )
        return compressed

    async def _maybe_summarize(self, turns: list[dict]) -> tuple[list[dict], Any | None]:
        """Summarize oldest turns if estimated tokens exceed the effective threshold."""
        if self.summarizer_model is None or len(turns) < 4:
            return turns, None

        threshold = self._effective_summarize_token_threshold()
        compressed = turns
        episodic: Any | None = None
        turns_before = len(turns)
        for _ in range(3):
            if _total_tokens(compressed) <= threshold or len(compressed) < 4:
                break
            next_turns, episodic = await summarize_oldest_turns(
                compressed,
                summarizer_model=self.summarizer_model,
            )
            if episodic is None or len(next_turns) >= len(compressed):
                break
            compressed = next_turns

        if episodic is not None:
            logger.info(
                f"[SessionMemory] Auto-summarized to episodic summary "
                f"(hash={episodic.content_hash})"
            )
            try:
                from ..observability.context_events import emit_context_summarized

                await emit_context_summarized(
                    scope="session",
                    turns_before=turns_before,
                    turns_after=len(compressed),
                    artifact_refs=list(episodic.artifact_refs),
                    content_hash=episodic.content_hash,
                )
            except Exception as exc:
                logger.debug(f"SessionMemory context.summarized emit failed: {exc!r}")
        return compressed, episodic

    def add_turn(
        self,
        thread_id: str,
        query: str,
        output: str,
        pattern: str = "",
        metadata: dict | None = None,
    ) -> None:
        """Append one turn. Drops oldest when max_turns exceeded."""
        if not (
            callable(getattr(self.store, "get", None)) and callable(getattr(self.store, "put", None))
        ):
            raise TypeError(
                "SessionMemory.add_turn() requires a store with sync get/put; use await aadd_turn() instead.",
            )
        with self._sync_turn_lock:
            ns = self._ns(thread_id)
            key = "turns"
            try:
                item = self.store.get(ns, key)
                turns: list[dict] = item.value.get("turns", []) if item else []
            except Exception as exc:
                logger.warning(f"SessionMemory.add_turn read failed: {exc!r}")
                return

            turns.append(
                {
                    "q": query,
                    "a": output,
                    "p": pattern,
                    **(metadata or {}),
                }
            )
            turns = self._maybe_summarize_sync(turns)
            if len(turns) > self.max_turns:
                turns = _trim_turns_preserving_summaries(turns, self.max_turns)
            self.store.put(ns, key, {"turns": turns})

    async def aadd_turn(
        self,
        thread_id: str,
        query: str,
        output: str,
        pattern: str = "",
        metadata: dict | None = None,
    ) -> None:
        """Append one turn (async store). Summarize, trim, write, and hook — all under one lock."""
        async with self._turn_lock:
            # Hold the lock through summarize + aput so concurrent aadd_turn(thread_id) cannot interleave.
            ns = self._ns(thread_id)
            key = "turns"
            try:
                item = await self.store.aget(ns, key)
                turns: list[dict] = item.value.get("turns", []) if item else []
            except Exception as exc:
                logger.warning(f"SessionMemory.aadd_turn read failed: {exc!r}")
                return

            turns.append(
                {
                    "q": query,
                    "a": output,
                    "p": pattern,
                    **(metadata or {}),
                }
            )

            turns, episodic = await self._maybe_summarize(turns)
            if episodic is not None:
                await self._persist_episodic_summary(thread_id, episodic)

            if len(turns) > self.max_turns:
                turns = _trim_turns_preserving_summaries(turns, self.max_turns)
            await self.store.aput(ns, key, {"turns": turns})
            await self._notify_turns_hook(thread_id, turns)
            try:
                from ..observability.memory_events import emit_memory_session_write

                await emit_memory_session_write(
                    thread_id=thread_id,
                    query=query,
                    output=output,
                    turn_count=len(turns),
                    run_id=(metadata or {}).get("run_id"),
                    event_queue=None,
                )
            except Exception as exc:
                logger.debug(f"SessionMemory memory.session.write emit failed: {exc!r}")

    async def apop_last_turn(self, thread_id: str) -> int | None:
        """Remove the last persisted turn for *thread_id*.

        Returns the **new** turn count after removal, or ``None`` if there was nothing
        to pop or the store could not be updated.
        """
        async with self._turn_lock:
            ns = self._ns(thread_id)
            key = "turns"
            try:
                item = await self.store.aget(ns, key)
                turns: list[dict] = item.value.get("turns", []) if item else []
            except Exception as exc:
                logger.debug(f"SessionMemory.apop_last_turn read failed: {exc!r}")
                return None
            if not turns:
                return None
            turns.pop()
            try:
                await self.store.aput(ns, key, {"turns": turns})
            except Exception as exc:
                logger.warning(f"SessionMemory.apop_last_turn write failed: {exc!r}")
                return None
            await self._notify_turns_hook(thread_id, turns)
            return len(turns)

    @staticmethod
    def _format_turns(turns: list[dict], last_n: int) -> str:
        recent = turns[-last_n:]
        if not recent:
            return ""
        lines = ["## Conversation History"]
        for t in recent:
            if t.get("q") == _SUMMARY_MARKER:
                lines.append(f"Previous conversation summary: {t['a']}")
            else:
                lines.append(f"User: {t['q']}")
                lines.append(f"Assistant: {t['a']}")
        return "\n".join(lines)

    def format_context(self, thread_id: str, last_n: int = 3) -> str:
        """SYNC — InMemoryStore only. Use aformat_context() for async stores."""
        ns = self._ns(thread_id)
        try:
            item = self.store.get(ns, "turns")
            turns = item.value.get("turns", []) if item else []
        except Exception as exc:
            logger.debug(f"SessionMemory.format_context read failed: {exc!r}")
            return ""
        return self._format_turns(turns, last_n)

    async def aformat_context(self, thread_id: str, last_n: int = 3) -> str:
        """Async version — works with all store backends."""
        ns = self._ns(thread_id)
        try:
            item = await self.store.aget(ns, "turns")
            turns = item.value.get("turns", []) if item else []
        except Exception as exc:
            logger.debug(f"SessionMemory.aformat_context read failed: {exc!r}")
            return ""
        return self._format_turns(turns, last_n)

    async def aclear_thread(self, thread_id: str) -> None:
        """Remove persisted turns for *thread_id* (short-term session memory key)."""
        ns = self._ns(thread_id)
        key = "turns"
        if hasattr(self.store, "adelete"):
            await self.store.adelete(ns, key)
            return
        if hasattr(self.store, "aput"):
            await self.store.aput(ns, key, {"turns": []})
            return
        try:
            delete = getattr(self.store, "delete", None)
            if callable(delete):
                delete(ns, key)
                return
            put = getattr(self.store, "put", None)
            if callable(put):
                put(ns, key, {"turns": []})
        except Exception as exc:
            logger.warning(f"SessionMemory.aclear_thread fallback failed: {exc!r}")
