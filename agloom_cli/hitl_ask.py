"""Build :class:`~agloom_cli.hitl_ask_types.AskUserRequest` payloads for HITL triple gates."""

from __future__ import annotations

import uuid

from .hitl_ask_types import AskUserRequest, Choice


def new_hitl_tool_call_id(raw: str | None) -> str:
    """Return a non-empty correlation id for ``AskUserRequest.tool_call_id``."""
    s = (raw or "").strip()
    return s if s else uuid.uuid4().hex


def build_hitl_triple_ask_request(
    *,
    tool_call_id: str,
    prompt_text: str,
    choice_labels: tuple[str, str, str],
    rich_prompt_default: str = "2",
    focus_choice_index: int | None = None,
) -> AskUserRequest:
    """One multiple-choice question with stable values ``accept`` / ``reject`` / ``allowlist``."""
    r1, r2, r3 = choice_labels
    choices: list[Choice] = [
        {"value": "accept", "label": r1},
        {"value": "reject", "label": r2},
        {"value": "allowlist", "label": r3},
    ]
    req: AskUserRequest = {
        "type": "ask_user",
        "tool_call_id": tool_call_id,
        "questions": [
            {
                "question": prompt_text,
                "type": "multiple_choice",
                "choices": choices,
                "required": True,
            }
        ],
        "rich_prompt_default": rich_prompt_default,
    }
    if focus_choice_index is not None:
        req["focus_choice_index"] = focus_choice_index
    return req


def triple_answer_to_token(result_answers: list[str]) -> str:
    """First answer token, normalized for :func:`agloom_cli.hitl._normalize_triple_choice`."""
    if not result_answers:
        return "reject"
    return (result_answers[0] or "reject").strip().lower()
