"""Prompt composition — core vs CLI workspace layers."""

from __future__ import annotations

from agloom.prompts.core import (
    ANSWER_CONTRACT_MARKER,
    CLI_WORKSPACE_SYSTEM_PROMPT,
    DEFAULT_SYSTEM_PROMPT,
    compose_agent_system_prompt,
)
from agloom.unified_agent import resolve_system_prompt


def test_compose_default_includes_answer_contract() -> None:
    sp = compose_agent_system_prompt(None, cli_tools=False)
    assert DEFAULT_SYSTEM_PROMPT.strip() in sp
    assert ANSWER_CONTRACT_MARKER in sp


def test_compose_cli_tools_uses_workspace_persona() -> None:
    sp = compose_agent_system_prompt(None, cli_tools=True)
    assert CLI_WORKSPACE_SYSTEM_PROMPT.strip() in sp
    assert "terminal workspace" in sp
    assert ANSWER_CONTRACT_MARKER in sp


def test_compose_custom_yaml_once_contract() -> None:
    custom = "You are a domain expert for billing."
    sp = compose_agent_system_prompt(custom, cli_tools=True)
    assert custom in sp
    assert ANSWER_CONTRACT_MARKER in sp
    assert sp.count(ANSWER_CONTRACT_MARKER) == 1


def test_resolve_system_prompt_cli_tools_flag() -> None:
    sp = resolve_system_prompt(None, cli_tools=True)
    assert isinstance(sp, str)
    assert "autonomous programming assistant" in sp
