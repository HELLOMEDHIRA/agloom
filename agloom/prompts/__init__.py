"""Prompt constants and composition helpers."""

from .core import (
    ANSWER_CONTRACT_MARKER,
    CLI_WORKSPACE_SYSTEM_PROMPT,
    DEFAULT_SYSTEM_PROMPT,
    GLOBAL_ANSWER_CONTRACT_APPENDIX,
    compose_agent_system_prompt,
    is_explicit_user_system_prompt,
    resolve_system_prompt_base,
)

__all__ = [
    "ANSWER_CONTRACT_MARKER",
    "CLI_WORKSPACE_SYSTEM_PROMPT",
    "DEFAULT_SYSTEM_PROMPT",
    "GLOBAL_ANSWER_CONTRACT_APPENDIX",
    "compose_agent_system_prompt",
    "resolve_system_prompt_base",
]
