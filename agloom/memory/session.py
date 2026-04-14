"""Short-term conversation memory scoped to a thread_id with auto-summarization."""

from __future__ import annotations

import time
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


def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken if available, else char approximation."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
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

    Auto-summarization (enabled by default):
      When accumulated tokens exceed `summarize_threshold`, the oldest
      70% of turns are compressed into a single summary turn via an LLM
      call. This preserves context that would otherwise be dropped.
    """

    def __init__(
        self,
        store: Any = None,
        max_turns: int = 20,
        auto_summarize: bool = True,
        summarize_threshold: int = 200_000,
        summarizer_model: Any = None,
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

    def _ns(self, thread_id: str) -> tuple:
        return _NAMESPACE_PREFIX + (thread_id,)

    async def _maybe_summarize(self, turns: list[dict]) -> list[dict]:
        """Summarize oldest turns if total tokens exceed threshold.

        Returns the (possibly compressed) turn list. Never raises —
        falls back to the original list on any error.
        """
        if not self.auto_summarize or self.summarizer_model is None:
            return turns
        if len(turns) < 4:
            return turns

        total = _total_tokens(turns)
        if total <= self.summarize_threshold:
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
                "q": query[:500],
                "a": output[:1000],
                "p": pattern,
                **(metadata or {}),
            }
        )
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
                "q": query[:500],
                "a": output[:1000],
                "p": pattern,
                **(metadata or {}),
            }
        )

        turns = await self._maybe_summarize(turns)

        if len(turns) > self.max_turns:
            turns = turns[-self.max_turns :]
        await self.store.aput(ns, key, {"turns": turns})

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
