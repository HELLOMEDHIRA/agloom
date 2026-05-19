"""System prompt building blocks for agloom agents.

Layers (lowest → highest precedence at runtime):

1. **DEFAULT_SYSTEM_PROMPT** — generic core for library/API/embed use (no terminal assumptions).
2. **CLI_WORKSPACE_SYSTEM_PROMPT** — default persona when ``cli_tools`` is enabled and no custom prompt is set.
3. **User / YAML ``system_prompt``** — ``ai.system_prompt`` or top-level ``system_prompt`` in
   ``.agloom/agloom.yaml`` (replaces 1–2 at runtime; persisted across CLI restarts when set in YAML
   or via ``/system`` in the TUI). Pattern appendices still apply.
4. **CLI_TOOLS_SYSTEM_APPENDIX** — appended in ``create_agent`` when bundled workspace tools are active.
5. **Pattern appendices** — e.g. ``REACT_TOOL_DISCIPLINE`` in ``patterns/react.py`` (tool-loop only).

Pattern handlers may add further instructions; they should not contradict the answer contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.messages import SystemMessage

_PROMPTS_DIR = Path(__file__).resolve().parent


def _load_prompt_file(name: str) -> str:
    path = _PROMPTS_DIR / name
    return path.read_text(encoding="utf-8").strip() + "\n"

# Marker checked before re-appending the global contract (idempotent compose).
ANSWER_CONTRACT_MARKER = "=== Answer contract"

DEFAULT_SYSTEM_PROMPT = """You are a capable AI assistant running inside the agloom agent runtime.

## Mission
- Understand the user's goal and deliver a direct, accurate **final answer**.
- Use tools only when they materially improve correctness (files, commands, live data, calculations).
- When tools are unavailable or unnecessary, answer from reasoning alone.

## Final answer (always)
- Write clear prose in the user's language. The final message must **stand alone**.
- Never say "shown above/below", "in the trace/panel", or "as displayed in the UI".
- Never paste raw tool JSON, pseudo tool calls, or internal protocol markers as the answer.
- Never tell the user to invoke tools themselves — only the runtime can run tools in this session.
- After tools return: **synthesize** what matters; do not dump entire tool outputs unless the user asked for verbatim content.
- If data is missing, say so plainly; use a tool or ask one focused question — do not invent file contents or command output.

## Quality
- Prefer correctness over verbosity; expand only when the user asks for depth or teaching.
- State assumptions when the request is ambiguous.
"""

CLI_WORKSPACE_SYSTEM_PROMPT = _load_prompt_file("cli_workspace_prompt.txt")

GLOBAL_ANSWER_CONTRACT_APPENDIX = f"""

{ANSWER_CONTRACT_MARKER} (non-negotiable) ===
- Final message = standalone prose for the user (not pointers to UI/tool panels).
- No tool-call JSON as assistant text; use native tool calls when tools are required.
- After tools: synthesize; do not repeat full tool payloads unless verbatim review was requested.
"""


def resolve_system_prompt_base(system_prompt: Any, *, cli_tools: bool = False) -> str:
    """Resolve string system prompt before pattern-specific appendices."""
    if callable(system_prompt) and not isinstance(system_prompt, str):
        raise TypeError("resolve_system_prompt_base does not accept callables")
    if isinstance(system_prompt, SystemMessage):
        content = system_prompt.content
        system_prompt = content if isinstance(content, str) else str(content)
    if isinstance(system_prompt, str) and system_prompt.strip():
        return system_prompt.strip()
    if cli_tools:
        return CLI_WORKSPACE_SYSTEM_PROMPT
    return DEFAULT_SYSTEM_PROMPT


def is_explicit_user_system_prompt(system_prompt: Any) -> bool:
    """True when the caller passed a non-empty prompt (YAML, CLI flag, or ``command.config.set``)."""
    if system_prompt is None:
        return False
    if isinstance(system_prompt, SystemMessage):
        content = system_prompt.content
        return bool(isinstance(content, str) and content.strip())
    if isinstance(system_prompt, str):
        return bool(system_prompt.strip())
    return True


def compose_agent_system_prompt(system_prompt: Any, *, cli_tools: bool = False) -> str | Any:
    """Return callable unchanged; otherwise base prompt + global answer contract.

    When ``system_prompt`` is omitted, the built-in default is chosen (CLI workspace text if
    ``cli_tools`` else core default). When the user supplies YAML or ``--system-prompt``, that
    text is used as-is for the body (still gets the answer-contract footer unless already present).
    """
    if callable(system_prompt) and not isinstance(system_prompt, str):
        return system_prompt
    base = resolve_system_prompt_base(system_prompt, cli_tools=cli_tools)
    if ANSWER_CONTRACT_MARKER in base:
        return base
    return base.rstrip() + GLOBAL_ANSWER_CONTRACT_APPENDIX
