"""Wire FeedbackStore, AutoEvaluator, and TrendDetector into the agent config."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .evaluator import AutoEvaluator
from .store import FeedbackStore
from .trends import TrendDetector
from .user_feedback import (
    NoOpFeedbackHandler,
    UserFeedbackHandler,
)

if TYPE_CHECKING:
    from ..memory.store import LongTermStore

from ..logging_utils import get_logger

logger = get_logger(__name__)


def build_feedback_system(
    llm: Any,
    long_term_store: LongTermStore,
    agent_name: str,
    feedback_handler: UserFeedbackHandler | None = None,
    skill_lifecycle: Any | None = None,  # SkillLifecycleManager (optional)
    trend_every_n: int = 100,
    llm_timeout: float = 30.0,
    structured_max_retries: int = 2,
    low_score_threshold: float = 0.40,
) -> dict:
    """
    Build store, auto-evaluator, trend detector, and handler for merging into agent config.

    Returns:
        Dict with keys ``feedback_store``, ``auto_evaluator``, ``trend_detector``,
        ``feedback_handler`` (defaults to ``NoOpFeedbackHandler``). If ``skill_lifecycle``
        is set, skill-failure signals from the store are forwarded to it.
    """
    feedback_store = FeedbackStore(
        store=long_term_store,
        agent_name=agent_name,
    )

    if skill_lifecycle is not None:

        async def _skill_failure_cb(skill_name: str, run_id: str) -> None:
            await skill_lifecycle._update_usage(skill_name, success=False)
            logger.debug(
                f"FeedbackSystem [{agent_name}]: skill failure signal "
                f"forwarded → lifecycle for '{skill_name}' (run {run_id})"
            )

        feedback_store.on_skill_failure(_skill_failure_cb)
        logger.debug(f"FeedbackSystem [{agent_name}]: skill failure → lifecycle callback registered")

    auto_evaluator = AutoEvaluator(
        llm=llm,
        feedback_store=feedback_store,
        agent_name=agent_name,
        llm_timeout=llm_timeout,
        structured_max_retries=structured_max_retries,
        low_score_threshold=low_score_threshold,
    )

    trend_detector = TrendDetector(
        llm=llm,
        feedback_store=feedback_store,
        agent_name=agent_name,
        run_every=trend_every_n,
        llm_timeout=llm_timeout,
        structured_max_retries=structured_max_retries,
    )

    handler = feedback_handler or NoOpFeedbackHandler()
    handler_name = type(handler).__name__
    if isinstance(handler, NoOpFeedbackHandler):
        logger.debug(f"FeedbackSystem [{agent_name}]: no feedback_handler provided — using NoOpFeedbackHandler")
    else:
        logger.info(f"FeedbackSystem [{agent_name}]: feedback_handler = {handler_name}")

    return {
        "feedback_store": feedback_store,
        "auto_evaluator": auto_evaluator,
        "trend_detector": trend_detector,
        "feedback_handler": handler,
    }


def run_fresh_feedback_hooks(
    config: dict,
    result: Any,
    query: str,
    skill_used: str | None = None,
) -> None:
    """Fire all post-run feedback hooks as background tasks."""
    evaluator: AutoEvaluator | None = config.get("auto_evaluator")
    detector: TrendDetector | None = config.get("trend_detector")
    lifecycle: Any | None = config.get("skill_lifecycle")

    if evaluator:
        run_id = evaluator.evaluate(result, query, skill_used)
        try:
            object.__setattr__(result, "run_id", run_id)
        except Exception:
            pass

    if detector:
        detector.on_run_complete()

    if lifecycle:
        lifecycle.on_run_complete(
            success=getattr(result, "success", True),
            applied_skill=skill_used,
        )


async def apply_user_feedback(
    config: dict,
    run_id: str,
    rating: str,
    comment: str = "",
    correct: str = "",
    metadata: dict | None = None,
) -> None:
    """Route user feedback through FeedbackStore and UserFeedbackHandler."""
    store: FeedbackStore | None = config.get("feedback_store")
    handler: UserFeedbackHandler | None = config.get("feedback_handler")

    if store:
        await store.apply_user_feedback(
            run_id=run_id,
            rating=rating,
            comment=comment,
            correct=correct,
            metadata=metadata,
        )

    if handler and not isinstance(handler, NoOpFeedbackHandler):
        await handler.on_feedback(
            run_id=run_id,
            rating=rating,
            comment=comment,
            correct=correct,
            metadata=metadata,
        )
