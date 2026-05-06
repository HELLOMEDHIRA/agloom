"""Lightweight types for the ask-user style HITL interrupt protocol.

Structured payloads (``AskUserRequest``) let Textual and other UIs render gates without
parsing ad-hoc prose. ``tool_call_id`` correlates the prompt to the originating tool
invocation when the runtime supplies it.

``label`` on :class:`Choice` is an optional display override; ``value`` is the stable
token returned in :class:`AskUserAnswered` (e.g. ``accept`` / ``reject`` / ``allowlist``).
"""

from __future__ import annotations

from typing import Literal, NotRequired, Required, TypedDict


class Choice(TypedDict, total=False):
    """One option for a multiple-choice question."""

    value: str
    """Stable answer token (returned in ``AskUserAnswered.answers``)."""

    label: NotRequired[str]
    """Optional button / line label; defaults to a humanized ``value``."""


class Question(TypedDict, total=False):
    """A single question in an :class:`AskUserRequest`."""

    question: str
    type: Literal["text", "multiple_choice"]
    choices: NotRequired[list[Choice]]
    required: NotRequired[bool]


class AskUserRequest(TypedDict, total=False):
    """Request payload for a user interrupt (HITL gates, clarifications, …)."""

    type: Required[Literal["ask_user"]]
    questions: Required[list[Question]]
    tool_call_id: Required[str]
    """ID for the originating tool call when known; otherwise a synthetic id."""

    rich_prompt_default: NotRequired[str]
    """Rich console only: ``Prompt.ask`` default, typically ``\"1\"``–``\"3\"``."""

    focus_choice_index: NotRequired[int]
    """Textual only: 1-based index of the choice button to focus on mount."""


class AskUserAnswered(TypedDict):
    """User submitted answers — one string per question, in order."""

    type: Literal["answered"]
    answers: list[str]


class AskUserCancelled(TypedDict):
    """User dismissed the prompt without submitting."""

    type: Literal["cancelled"]


AskUserWidgetResult = AskUserAnswered | AskUserCancelled
"""Result type for modal / async HITL UI implementations."""
