"""Semantic query cache: Qdrant + embeddings, pattern-scoped TTL, async-safe sync client via thread pool.

Use ``create_cache`` to build the dict passed as ``query_cache`` to ``create_agent``.
``cache_get`` / ``cache_set`` are invoked from ``run_fresh`` after classification.

``create_agent`` defaults ``query_cache=None`` to :func:`default_query_cache` (in-memory Qdrant +
:class:`HashEmbeddings`, no ML downloads). Pass ``query_cache=False`` to disable caching entirely.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointIdsList,
    PointStruct,
    VectorParams,
)

from .logging_utils import get_logger

logger = get_logger(__name__)

_qdrant_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="qdrant")

CACHE_TTL: dict[str, int] = {
    "DIRECT": 86400,
    "REACT": 3600,
    "SUPERVISOR": 1800,
    "PIPELINE": 3600,
    "PLANNER_EXECUTOR": 1800,
    "REFLECTION": 0,
    "SWARM": 1800,
    "BLACKBOARD": 0,
    "HYBRID_DAG": 0,
}

COLLECTION_NAME = "query_cache"


class HashEmbeddings(Embeddings):
    """Deterministic pseudo-embeddings (SHA-256 expansion) for the default cache.

    Same UTF-8 string always maps to the same unit vector so repeated identical queries can hit
    the semantic cache without installing ``sentence-transformers``. Near-duplicates do not match
    unless they share the same bytes.
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    @staticmethod
    def _vector(text: str, dim: int = 384) -> list[float]:
        raw: list[float] = []
        buf = hashlib.sha256(text.encode("utf-8", errors="surrogateescape")).digest()
        i = 0
        while len(raw) < dim:
            buf = hashlib.sha256(buf + str(i).encode()).digest()
            i += 1
            for b in buf:
                if len(raw) >= dim:
                    break
                raw.append((b / 127.5) - 1.0)
        vec = raw[:dim]
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


def default_query_cache() -> dict:
    """In-memory Qdrant + :class:`HashEmbeddings` (no optional ML stack)."""
    return create_cache(HashEmbeddings(), similarity_threshold=0.999)


def create_cache(
    embeddings: Embeddings,
    similarity_threshold: float = 0.92,
    qdrant_url: str | None = None,
    qdrant_api_key: str | None = None,
    vector_size: int = 384,
) -> dict:
    """Open or create the Qdrant collection and return ``{"client", "embeddings", "threshold"}``."""
    if qdrant_url:
        client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        logger.event(f"[Cache] Persistent Qdrant at {qdrant_url}")
    else:
        client = QdrantClient(":memory:")
        logger.event("[Cache] In-memory Qdrant (wiped on app stop)")

    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )

    return {
        "client": client,
        "embeddings": embeddings,
        "threshold": similarity_threshold,
    }


async def cache_get(cache: dict, query: str, pattern: str) -> dict | None:
    """
    Semantic similarity search with TTL check.
    Qdrant client is sync — offloaded to a thread pool to avoid blocking the event loop.
    """
    ttl = CACHE_TTL.get(pattern, 0)
    if ttl == 0:
        return None

    client = cache["client"]
    loop = asyncio.get_running_loop()
    vector = await cache["embeddings"].aembed_query(query)

    response = await loop.run_in_executor(
        _qdrant_pool,
        partial(
            client.query_points,
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=1,
            score_threshold=cache["threshold"],
            with_payload=True,
        ),
    )
    hits = response.points

    if not hits:
        return None

    hit = hits[0]
    payload = hit.payload
    cached_at = payload.get("cached_at", 0)
    age = time.time() - cached_at

    if age > ttl:
        await loop.run_in_executor(
            _qdrant_pool,
            partial(
                client.delete,
                collection_name=COLLECTION_NAME,
                points_selector=PointIdsList(points=[hit.id]),
            ),
        )
        logger.event(f"[Cache] EXPIRED + DELETED — id={hit.id}, age={age:.0f}s > TTL={ttl}s")
        return None

    logger.event(f"[Cache] HIT — similarity={hit.score:.3f}, age={age:.0f}s / TTL={ttl}s, pattern={pattern}")
    return payload


async def cache_set(cache: dict, query: str, pattern: str, output: str) -> None:
    """Store query + result. Qdrant upsert offloaded to thread pool."""
    if CACHE_TTL.get(pattern, 0) == 0:
        return

    loop = asyncio.get_running_loop()
    vector = await cache["embeddings"].aembed_query(query)
    point = PointStruct(
        id=str(uuid.uuid4()),
        vector=vector,
        payload={
            "query": query,
            "output": output,
            "pattern": pattern,
            "cached_at": time.time(),
        },
    )

    await loop.run_in_executor(
        _qdrant_pool,
        partial(
            cache["client"].upsert,
            collection_name=COLLECTION_NAME,
            points=[point],
        ),
    )
    logger.event(f"[Cache] STORED — pattern={pattern}, TTL={CACHE_TTL[pattern]}s, query='{query}'")


async def cache_cleanup(cache: dict) -> int:
    """Scan all records, delete expired ones. Qdrant calls offloaded to thread pool."""
    client, deleted, offset = cache["client"], 0, None
    loop = asyncio.get_running_loop()

    while True:
        results, next_offset = await loop.run_in_executor(
            _qdrant_pool,
            partial(
                client.scroll,
                collection_name=COLLECTION_NAME,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            ),
        )

        expired_ids = [
            p.id
            for p in results
            if time.time() - p.payload.get("cached_at", 0) > CACHE_TTL.get(p.payload.get("pattern", "DIRECT"), 0)
        ]

        if expired_ids:
            await loop.run_in_executor(
                _qdrant_pool,
                partial(
                    client.delete,
                    collection_name=COLLECTION_NAME,
                    points_selector=PointIdsList(points=expired_ids),
                ),
            )
            deleted += len(expired_ids)
            logger.event(f"[Cache] Cleanup — deleted {len(expired_ids)} records.")

        if next_offset is None:
            break
        offset = next_offset

    logger.event(f"[Cache] Cleanup complete — {deleted} total records removed.")
    return deleted


async def start_cleanup_loop(cache: dict, interval_seconds: int = 1800) -> None:
    """Background cleanup — wire as asyncio.create_task() at app startup."""
    logger.event(f"[Cache] Cleanup loop started (interval={interval_seconds}s)")
    while True:
        await asyncio.sleep(interval_seconds)
        await cache_cleanup(cache)
