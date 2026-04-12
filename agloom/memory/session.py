"""Short-term conversation memory scoped to a thread_id."""

from __future__ import annotations

from typing import Any

from ..logging_utils import get_logger

logger = get_logger(__name__)

_NAMESPACE_PREFIX = ("session",)


class SessionMemory:
    """
    Short-term memory scoped to a thread_id.
    Each thread → one key in the store, value = {turns: [...]}
    """

    def __init__(
        self,
        store: Any = None,
        max_turns: int = 20,
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

    def _ns(self, thread_id: str) -> tuple:
        return _NAMESPACE_PREFIX + (thread_id,)

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
        if len(turns) > self.max_turns:
            turns = turns[-self.max_turns :]
        await self.store.aput(ns, key, {"turns": turns})

    def format_context(self, thread_id: str, last_n: int = 3) -> str:
        """SYNC — InMemoryStore only. Use aformat_context() for async stores."""
        ns = self._ns(thread_id)
        try:
            item = self.store.get(ns, "turns")
            turns = item.value.get("turns", []) if item else []
        except Exception as exc:
            logger.debug(f"SessionMemory.format_context read failed: {exc!r}")
            return ""

        recent = turns[-last_n:]
        if not recent:
            return ""
        lines = ["## Conversation History"]
        for t in recent:
            lines.append(f"User: {t['q']}")
            lines.append(f"Assistant: {t['a']}")
        return "\n".join(lines)

    async def aformat_context(self, thread_id: str, last_n: int = 3) -> str:
        """Async version — works with all store backends."""
        ns = self._ns(thread_id)
        try:
            item = await self.store.aget(ns, "turns")
            turns = item.value.get("turns", []) if item else []
        except Exception as exc:
            logger.debug(f"SessionMemory.aformat_context read failed: {exc!r}")
            return ""

        recent = turns[-last_n:]
        if not recent:
            return ""
        lines = ["## Conversation History"]
        for t in recent:
            lines.append(f"User: {t['q']}")
            lines.append(f"Assistant: {t['a']}")
        return "\n".join(lines)
