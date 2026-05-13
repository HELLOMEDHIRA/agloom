"""Classifier prompt must not use str.format on untrusted query / tool text."""

from __future__ import annotations

from agloom.classifier import CLASSIFIER_PROMPT


def test_classifier_prompt_uses_replace_not_format_for_user_text() -> None:
    """Braces in the user query must not be interpreted as format fields."""
    query = 'Explain dict {key: value} and literal {tools} in Python'
    tools_desc = "none"
    prompt = CLASSIFIER_PROMPT.replace("{tools}", tools_desc).replace("{query}", query)
    assert "dict {key: value}" in prompt
    assert "literal {tools}" in prompt
    assert query in prompt
