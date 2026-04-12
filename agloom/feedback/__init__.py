"""Feedback subsystem: auto-evaluation, trend detection, and user feedback."""

from .evaluator import AutoEvaluator, EvalScore, RunRecord
from .store import FeedbackStore
from .trends import TrendDetector
from .user_feedback import (
    CompositeHandler,
    LTSFeedbackHandler,
    NoOpFeedbackHandler,
    UserFeedbackHandler,
    WebhookFeedbackHandler,
)

__all__ = [
    "AutoEvaluator",
    "CompositeHandler",
    "EvalScore",
    "FeedbackStore",
    "LTSFeedbackHandler",
    "NoOpFeedbackHandler",
    "RunRecord",
    "TrendDetector",
    "UserFeedbackHandler",
    "WebhookFeedbackHandler",
]
