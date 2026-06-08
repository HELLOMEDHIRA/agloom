"""Short-term conversation memory scoped to a thread_id with auto-summarization."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ..logging_utils import get_logger

logger = get_logger(__name__)

_NAMESPACE_PREFIX = ("session",)

_SUMMARY_MARKER = "[SUMMARY]"

_SUMMARIZE_PROMPT = (
    "Summarize the following conversation history into a concise summary.\n"
    "Preserve: key decisions, user preferences, specific values/names/IDs mentioned, and any pending tasks.\n"
    "Omit: greetings, filler, redundant re-statements.\n\n"
    "Conversation:\n{turns_text}\n\nSummary:"
)

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


class SessionMemory:
    """
    Short-term memory scoped to a thread_id.
    Each thread -> one key in the store, value = {turns: [...]}

    Each turn stores full ``q`` / ``a`` text as provided. Prompt injection via
    :func:`~agloom.memory.build_memory_context` may still cap rendered size with ``max_chars``.

    Auto-summarization (enabled by default):
      When accumulated tokens exceed a threshold, the oldest 70% of turns are compressed
      into a single summary turn via an LLM call. The threshold is either
      ``max(1, int(0.8 * summarize_max_tokens_budget))`` when *summarize_max_tokens_budget*
      is set (session / model output cap), or ``summarize_threshold`` otherwise (default
      200_000 estimated tokens).
    """

    def __init__(
        self,
        store: Any = None,
        max_turns: int = 50,
        auto_summarize: bool = True,
        summarize_threshold: int = 200_000,
        summarizer_model: Any = None,
        *,
        summarize_max_tokens_budget: int | None = None,
        on_turns_async: Callable[[str, list[dict[str, Any]]], Awaitable[None]] | None = None,
        agp_session_key: str | None = None,
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
        self.auto_summarize = auto_summarize
        self.summarize_threshold = summarize_threshold
        self.summarizer_model = summarizer_model
        self.summarize_max_tokens_budget = summarize_max_tokens_budget
        self.on_turns_async = on_turns_async
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
        """Estimated-token ceiling before compressing oldest turns (see class docstring)."""
        if self.summarize_max_tokens_budget is not None:
            b = self.summarize_max_tokens_budget
            if b > 0:
                return max(1, int(b * 0.8))
        return self.summarize_threshold

    def _maybe_summarize_sync(self, turns: list[dict]) -> list[dict]:
        """Sync summarize for ``add_turn`` (uses ``invoke`` when a model is configured)."""
        if not self.auto_summarize or self.summarizer_model is None:
            return turns
        if len(turns) < 4:
            return turns

        total = _total_tokens(turns)
        threshold = self._effective_summarize_token_threshold()
        if total <= threshold:
            return turns

        split_idx = max(1, int(len(turns) * 0.7))
        oldest = turns[:split_idx]
        recent = turns[split_idx:]
        prompt = _SUMMARIZE_PROMPT.format(turns_text=_turns_to_text(oldest))

        try:
            from langchain_core.messages import HumanMessage

            invoke = getattr(self.summarizer_model, "invoke", None)
            if not callable(invoke):
                return turns
            resp = invoke([HumanMessage(content=prompt)])
            content = getattr(resp, "content", resp)
            summary = content if isinstance(content, str) else str(content)
            return [{"q": _SUMMARY_MARKER, "a": summary.strip(), "p": "summary"}] + recent
        except Exception as exc:
            logger.warning(f"[SessionMemory] sync auto-summarize failed ({exc!r}) — keeping original turns.")
            return turns

    async def _maybe_summarize(self, turns: list[dict]) -> list[dict]:
        """Summarize oldest turns if estimated tokens exceed the effective threshold.

        Returns the (possibly compressed) turn list. Never raises —
        falls back to the original list on any error.
        """
        if not self.auto_summarize or self.summarizer_model is None:
            return turns
        if len(turns) < 4:
            return turns

        total = _total_tokens(turns)
        threshold = self._effective_summarize_token_threshold()
        if total <= threshold:
            return turns

        split_idx = max(1, int(len(turns) * 0.7))
        oldest = turns[:split_idx]
        recent = turns[split_idx:]

        oldest_text = _turns_to_text(oldest)
        prompt = _SUMMARIZE_PROMPT.format(turns_text=oldest_text)

        try:
            t0 = time.perf_counter()
            from langchain_core.messages import HumanMessage

            resp = await self.summarizer_model.ainvoke([HumanMessage(content=prompt)])
            summary = resp.content if isinstance(resp.content, str) else str(resp.content)
            dur_ms = round((time.perf_counter() - t0) * 1000, 1)

            summary_turn = {"q": _SUMMARY_MARKER, "a": summary.strip(), "p": "summary"}
            compressed = [summary_turn] + recent

            old_tokens = _total_tokens(oldest)
            new_tokens = _count_tokens(summary)
            logger.info(
                f"[SessionMemory] Auto-summarized {len(oldest)} turns "
                f"({old_tokens} tokens -> {new_tokens} tokens) in {dur_ms}ms. "
                f"Kept {len(recent)} recent turns."
            )
            return compressed

        except Exception as exc:
            logger.warning(f"[SessionMemory] Auto-summarize failed ({exc!r}) — keeping original turns.")
            return turns

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
                logger.debug(f"SessionMemory.add_turn read failed: {exc!r}")
                turns = []

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
                turns = turns[-self.max_turns :]
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
                logger.debug(f"SessionMemory.aadd_turn read failed: {exc!r}")
                turns = []

            turns.append(
                {
                    "q": query,
                    "a": output,
                    "p": pattern,
                    **(metadata or {}),
                }
            )

            turns = await self._maybe_summarize(turns)

            if len(turns) > self.max_turns:
                turns = turns[-self.max_turns :]
            await self.store.aput(ns, key, {"turns": turns})
            await self._notify_turns_hook(thread_id, turns)

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
