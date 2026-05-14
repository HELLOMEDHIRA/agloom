"""Classifier prompt must not use str.format on untrusted query / tool text."""

from __future__ import annotations

from agloom.classifier import CLASSIFIER_PROMPT, build_classifier_user_prompt


def test_classifier_prompt_uses_replace_not_format_for_user_text() -> None:
    """Braces in the user query must not be interpreted as format fields."""
    query = 'Explain dict {key: value} and literal {tools} in Python'
    tools_desc = "none"
    prompt = build_classifier_user_prompt(tools_desc=tools_desc, query=query)
    assert "dict {key: value}" in prompt
    assert "literal {tools}" in prompt
    assert query in prompt


def test_classifier_prompt_tool_description_braces_not_leak_query() -> None:
    """A ``{query}`` substring inside the synthesized tools block must stay literal."""
    query = "REAL_USER_QUESTION"
    tools_desc = "  - t1: mentions template {query} in docs"
    prompt = build_classifier_user_prompt(tools_desc=tools_desc, query=query)
    assert tools_desc in prompt
    assert "Query: REAL_USER_QUESTION" in prompt or "REAL_USER_QUESTION" in prompt.split("Query:")[-1]
    assert "mentions template REAL_USER_QUESTION" not in prompt


def test_legacy_double_replace_would_corrupt_tool_line() -> None:
    """Document why we avoid ``replace(tools)`` then ``replace(query)``."""
    query = "REAL_USER_QUESTION"
    tools_desc = "  - t1: see {query} placeholder in readme"
    broken = CLASSIFIER_PROMPT.replace("{tools}", tools_desc).replace("{query}", query)
    assert "see REAL_USER_QUESTION placeholder" in broken
    safe = build_classifier_user_prompt(tools_desc=tools_desc, query=query)
    assert "see {query} placeholder" in safe


class _T:
    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description


def test_build_classifier_user_prompt_matches_tool_list() -> None:
    tools = [_T("echo", "Says {query}"), _T("grep", "Finds text")]
    td = "\n".join(f"  - {t.name}: {getattr(t, 'description', '')}" for t in tools)
    q = "hello {tools} world"
    body = build_classifier_user_prompt(tools_desc=td, query=q)
    assert "Says {query}" in body
    assert "hello {tools} world" in body
