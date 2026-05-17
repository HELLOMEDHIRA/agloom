"""LTS-backed persistence for run feedback records and skill failure signals.

Corrections default to namespace ``("memory", agent_name, user_id|"shared")`` so
multi-tenant deployments should ensure ``RunRecord.user_id`` (via invoke-time
``user_id``) is set; otherwise all corrections share the ``"shared"`` bucket.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..memory.store import LongTermStore

if TYPE_CHECKING:
    from .evaluator import RunRecord

from ..logging_utils import get_logger

logger = get_logger(__name__)

FEEDBACK_NS_PREFIX = "feedback"

SkillFailureCallback = Callable[[str, str], Awaitable[None]]


def _run_record_time_key(meta: dict) -> str:
    """Lexicographic sort works for ISO-8601 ``created_at`` / ``rated_at``."""
    return str(meta.get("created_at") or meta.get("rated_at") or "")


class FeedbackStore:
    """Persistence layer for run feedback records."""

    def __init__(
        self,
        store: LongTermStore,
        agent_name: str,
    ) -> None:
        self._store = store
        self._ns = (FEEDBACK_NS_PREFIX, agent_name)
        self._agent = agent_name
        self._skill_failure_callbacks: list[SkillFailureCallback] = []

    async def save(self, record: RunRecord) -> None:
        """Upsert a RunRecord into LongTermStore."""
        await self._store.asave(
            namespace=self._ns,
            key=record.run_id,
            value=record.index_text(),
            metadata=record.model_dump(),
        )
        score_str = f"{record.score.overall():.2f}" if record.score else "n/a"
        logger.debug(f"FeedbackStore [{self._agent}]: saved run {record.run_id} score={score_str}")

    async def get(self, run_id: str) -> RunRecord | None:
        from .evaluator import RunRecord

        result = await self._store.aget(self._ns, run_id)
        if not result:
            return None
        meta = getattr(result, "value", {}) or {}
        try:
            return RunRecord(**meta)
        except Exception as e:
            logger.warning(f"FeedbackStore: failed to deserialise run {run_id}: {e}")
            return None

    async def get_recent(self, n: int = 100) -> list[dict]:
        """Return the *n* most recent run records by wall time (``created_at``), not embedding rank.

        Semantic search is used only as a wide retrieval pass; results are re-sorted chronologically.
        """
        fetch_k = max(n * 4, n + 80, 200)
        results = await self._store.asearch(
            namespace=self._ns,
            query="feedback run evaluation score query pattern",
            top_k=fetch_k,
        )
        records: list[dict] = []
        for r in results:
            meta = getattr(r, "value", {}) or {}
            if meta.get("run_id"):
                records.append(meta)
        records.sort(key=_run_record_time_key, reverse=True)
        return records[:n]

    async def apply_user_feedback(
        self,
        run_id: str,
        rating: str,
        comment: str = "",
        correct: str = "",
        metadata: dict | None = None,
    ) -> bool:
        """Enrich existing RunRecord with user rating. Returns False if run_id unknown."""

        existing = await self._store.aget(self._ns, run_id)
        if not existing:
            logger.warning(f"FeedbackStore [{self._agent}]: run_id '{run_id}' not found — cannot apply feedback")
            return False

        raw = getattr(existing, "value", {}) or {}
        meta_in = metadata or {}
        if (
            raw.get("user_rating") == rating
            and raw.get("user_comment") == comment
            and raw.get("user_correction") == correct
            and all(raw.get(k) == v for k, v in meta_in.items())
        ):
            logger.debug(f"FeedbackStore [{self._agent}]: idempotent skip for run {run_id}")
            return True

        raw.update(
            {
                "user_rating": rating,
                "user_comment": comment,
                "user_correction": correct,
                "rated_at": datetime.now(UTC).isoformat(),
                **(metadata or {}),
            }
        )

        await self._store.asave(
            namespace=self._ns,
            key=run_id,
            value=raw.get("memory", run_id),
            metadata=raw,
        )

        if correct:
            uid = str(raw.get("user_id") or "").strip() or "shared"
            await self._save_correction_memory(
                run_id=run_id,
                original_query=raw.get("query", ""),
                correction=correct,
                user_id=uid,
            )

        if rating in ("negative", "wrong", "bad", "incorrect"):
            skill = raw.get("skill_used")
            if skill:
                await self.signal_skill_failure(skill, run_id)

        logger.info(f"FeedbackStore [{self._agent}]: user feedback '{rating}' applied to run {run_id}")
        return True

    async def _save_correction_memory(
        self,
        run_id: str,
        original_query: str,
        correction: str,
        *,
        user_id: str = "shared",
    ) -> None:
        """Store correction as a memory fact retrievable by future similar queries."""
        uid = user_id.strip() or "shared"
        try:
            await self._store.asave(
                namespace=("memory", self._agent, uid),
                key=f"correction_{run_id}",
                value=(f"user correction: for query '{original_query[:80]}' the correct answer is: {correction[:200]}"),
                metadata={
                    "type": "user_correction",
                    "query": original_query,
                    "correction": correction,
                    "run_id": run_id,
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
            logger.debug(f"FeedbackStore [{self._agent}]: correction memory saved for run {run_id}")
        except Exception as e:
            logger.warning(f"FeedbackStore: failed to save correction memory: {e}")

    def on_skill_failure(self, callback: SkillFailureCallback) -> None:
        self._skill_failure_callbacks.append(callback)
        logger.debug(f"FeedbackStore [{self._agent}]: skill failure callback registered: {callback}")

    async def signal_skill_failure(self, skill_name: str, run_id: str = "") -> None:
        """Fire all registered skill failure callbacks. Errors never propagate."""
        for cb in self._skill_failure_callbacks:
            try:
                await cb(skill_name, run_id)
            except Exception as e:
                logger.warning(f"FeedbackStore: skill failure callback error for '{skill_name}': {e}")

    async def get_stats(self) -> dict:
        """Quick stats snapshot for logging/monitoring."""
        records = await self.get_recent(n=500)
        if not records:
            return {"total": 0}

        scores = [
            r["score"]["accuracy"] + r["score"]["completeness"] + r["score"]["efficiency"] + r["score"]["relevance"]
            for r in records
            if isinstance(r.get("score"), dict)
        ]
        avg = round(sum(scores) / (len(scores) * 4), 3) if scores else 0.0

        ratings = [r.get("user_rating") for r in records if r.get("user_rating")]
        positive = sum(1 for r in ratings if r in ("positive", "good", "correct"))
        negative = sum(1 for r in ratings if r in ("negative", "wrong", "bad"))

        return {
            "total": len(records),
            "scored": len(scores),
            "avg_score": avg,
            "user_rated": len(ratings),
            "user_positive": positive,
            "user_negative": negative,
        }
