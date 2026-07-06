"""Classifier prompt stays aligned with registered PatternType handlers."""

from __future__ import annotations

from agloom.src.classifier import CLASSIFIER_PROMPT
from agloom.src.models import PatternType
from agloom.src.unified_agent import _HANDLERS


def test_classifier_prompt_mentions_every_handler_pattern() -> None:
    for pattern in _HANDLERS:
        if pattern == PatternType.DIRECT:
            continue
        assert pattern.value in CLASSIFIER_PROMPT or pattern.name in CLASSIFIER_PROMPT
