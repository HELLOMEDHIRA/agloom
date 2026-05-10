"""Agent with custom tools — demonstrates REACT pattern with tool calling."""

import ast
import asyncio
import operator
import os

from langchain_core.tools import tool
from langchain_groq import ChatGroq

from agloom import create_agent

llm = ChatGroq(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    api_key=os.environ["GROQ_API_KEY"],
    temperature=0,
)

def _safe_calc(expression: str) -> float:
    """Arithmetic only (+ − × ÷ // % ** and parentheses). No eval()."""
    tree = ast.parse(expression.strip(), mode="eval")

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp):
            match node.op:
                case ast.UAdd():
                    return operator.pos(_eval(node.operand))
                case ast.USub():
                    return operator.neg(_eval(node.operand))
                case _:
                    raise ValueError("only plain numeric arithmetic is allowed")
        if isinstance(node, ast.BinOp):
            match node.op:
                case ast.Add():
                    return operator.add(_eval(node.left), _eval(node.right))
                case ast.Sub():
                    return operator.sub(_eval(node.left), _eval(node.right))
                case ast.Mult():
                    return operator.mul(_eval(node.left), _eval(node.right))
                case ast.Div():
                    return operator.truediv(_eval(node.left), _eval(node.right))
                case ast.FloorDiv():
                    return operator.floordiv(_eval(node.left), _eval(node.right))
                case ast.Mod():
                    return operator.mod(_eval(node.left), _eval(node.right))
                case ast.Pow():
                    return operator.pow(_eval(node.left), _eval(node.right))
                case _:
                    raise ValueError("only plain numeric arithmetic is allowed")
        raise ValueError("only plain numeric arithmetic is allowed")

    return _eval(tree)


@tool
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression and return the result."""
    return str(_safe_calc(expression))


@tool
def extract_keywords(text: str) -> str:
    """Extract key words from the given text."""
    stop = {"the", "a", "an", "is", "are", "was", "in", "on", "at", "to", "and", "or", "of"}
    words = [w.strip(".,!?") for w in text.lower().split() if len(w) > 2]
    return ", ".join(sorted({w for w in words if w not in stop}))


async def main():
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
