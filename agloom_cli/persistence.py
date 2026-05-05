"""CLI-only durable LangGraph checkpoint + store (SQLite files under ``<project>/.agloom``).

Library :func:`agloom.create_agent` is unchanged; only the CLI wires these backends.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Generator


@contextmanager
def cli_langgraph_sqlite(enable_memory: bool, storage_root: Path) -> Generator[tuple[Any, Any], None, None]:
    """Open SQLite checkpointer + store, or yield ``(None, None)`` when memory is off.

    Yields:
        ``(checkpointer, raw_graph_store)`` for :class:`~agloom.memory.LongTermStore`
        / :class:`~agloom.memory.SessionMemory`, or in-memory-off mode two ``None`` values.
    """
    if not enable_memory:
        yield (None, None)
        return

    storage_root.mkdir(parents=True, exist_ok=True)
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.store.sqlite import SqliteStore

    ckpt_path = storage_root / "checkpoints.sqlite"
    store_path = storage_root / "graph_store.sqlite"
    with ExitStack() as stack:
        saver = stack.enter_context(SqliteSaver.from_conn_string(str(ckpt_path)))
        graph_store = stack.enter_context(SqliteStore.from_conn_string(str(store_path)))
        yield (saver, graph_store)
