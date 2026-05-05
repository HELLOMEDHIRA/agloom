"""CLI-only durable LangGraph checkpoint + store (SQLite files under ``<project>/.agloom``).

Library :func:`agloom.create_agent` is unchanged; only the CLI wires these backends.

Uses LangGraph's **async** SQLite implementations so ``aput`` / checkpoint writes used by
agloom and skills work at runtime (sync ``SqliteStore`` does not implement async methods).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator


@asynccontextmanager
async def cli_langgraph_sqlite(
    enable_memory: bool, storage_root: Path
) -> AsyncGenerator[tuple[Any, Any], None]:
    """Open async SQLite checkpointer + store, or yield ``(None, None)`` when memory is off.

    Yields:
        ``(checkpointer, raw_graph_store)`` for :class:`~agloom.memory.LongTermStore`
        / :class:`~agloom.memory.SessionMemory`, or in-memory-off mode two ``None`` values.
    """
    if not enable_memory:
        yield (None, None)
        return

    storage_root.mkdir(parents=True, exist_ok=True)
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.store.sqlite.aio import AsyncSqliteStore

    ckpt_path = storage_root / "checkpoints.sqlite"
    store_path = storage_root / "graph_store.sqlite"
    async with AsyncSqliteSaver.from_conn_string(str(ckpt_path)) as saver:
        async with AsyncSqliteStore.from_conn_string(str(store_path)) as graph_store:
            yield (saver, graph_store)
