"""CLI-only durable LangGraph checkpoint + store (SQLite files under ``<project>/.agloom``).

Library :func:`agloom.create_agent` is unchanged; only the CLI wires these backends.

Uses LangGraph's **async** SQLite implementations so ``aput`` / checkpoint writes used by
agloom and skills work at runtime (sync ``SqliteStore`` does not implement async methods).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any


@asynccontextmanager
async def cli_langgraph_sqlite(
    enable_memory: bool, storage_root: Path
) -> AsyncGenerator[tuple[Any, Any], None]:
    """Open async SQLite LangGraph store; optionally the checkpointer for session memory.

    ``graph_store.sqlite`` is **always** opened so the CLI can persist harness/skills data under
    ``.agloom/`` even when ``--no-memory`` (no session checkpoint resume, no LT memory tools).

    Yields:
        ``(checkpointer, raw_graph_store)`` — *checkpointer* is ``None`` when memory is disabled.
    """
    storage_root.mkdir(parents=True, exist_ok=True)
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.store.sqlite.aio import AsyncSqliteStore

    store_path = storage_root / "graph_store.sqlite"
    async with AsyncSqliteStore.from_conn_string(str(store_path)) as graph_store:
        if enable_memory:
            ckpt_path = storage_root / "checkpoints.sqlite"
            async with AsyncSqliteSaver.from_conn_string(str(ckpt_path)) as saver:
                yield (saver, graph_store)
        else:
            yield (None, graph_store)
