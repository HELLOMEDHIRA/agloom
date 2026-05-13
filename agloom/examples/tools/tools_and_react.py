"""Agent with custom tools — demonstrates REACT pattern with tool calling.

Requires ``langchain-groq`` (``pip install langchain-groq``) and ``GROQ_API_KEY``.
The sample ``calculate`` tool uses a tiny guarded ``eval`` — fine for a demo, not for production.
"""

from __future__ import annotations

import asyncio
import os
import re

from langchain_core.tools import tool
from langchain_groq import ChatGroq

from agloom import create_agent


def _require_env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise SystemExit(f"Set {name} (e.g. export {name}=...) to run this example.")
    return v


def _groq_llm() -> ChatGroq:
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
    return ChatGroq(model=model, api_key=_require_env("GROQ_API_KEY"), temperature=0)


_SAFE_ARITH = re.compile(r"^[\d\s+\-*/.%()]+$")


@tool
def calculate(expression: str) -> str:
    """Evaluate a numeric expression (digits, whitespace, + - * / % ** and parentheses)."""
    expr = expression.strip()
    if not expr or not _SAFE_ARITH.match(expr):
        return "error: only digits, spaces, and + - * / % ** ( ) . are allowed"
    try:
        return str(eval(expr, {"__builtins__": {}}, {}))
    except Exception as exc:
        return f"error: {exc}"


@tool
def extract_keywords(text: str) -> str:
    """Extract key words from the given text."""
    stop = {"the", "a", "an", "is", "are", "was", "in", "on", "at", "to", "and", "or", "of"}
    words = [w.strip(".,!?") for w in text.lower().split() if len(w) > 2]
    return ", ".join(sorted({w for w in words if w not in stop}))


async def main() -> None:
    llm = _groq_llm()
    agent = await create_agent(
        model=llm,
        tools=[calculate, extract_keywords],
        name="tool-agent",
    )

    result = await agent.ainvoke("Use the calculate tool to compute (25 * 4) + 17")

    print(f"Pattern: {result.pattern_used.value}")
    print(f"Output:  {result.output}")
    print("\nStep trace:")
    for step in result.steps:
        print(f"  [{step.type.value:12s}] {step.name} — {step.duration_ms}ms")


if __name__ == "__main__":
    asyncio.run(main())
