"""Tool discovery — auto-load tools from .py files."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any


def discover_tools(tools_dir: Path) -> list:
    """Auto-discover tools from a directory of Python files.

    Looks for:
    - Functions decorated with @tool
    - Functions with type hints → auto-converted to tools

    Args:
        tools_dir: Directory containing .py files with tool definitions

    Returns:
        List of BaseTool instances
    """
    from langchain_core.tools import BaseTool, StructuredTool

    tools: list[BaseTool] = []

    if not tools_dir.exists():
        return tools

    for py_file in tools_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue

        file_tools = load_tools_from_file(py_file)
        tools.extend(file_tools)

    return tools


def load_tools_from_file(path: Path) -> list:
    """Load tools from a single Python file."""
    from langchain_core.tools import BaseTool, StructuredTool

    tools: list[BaseTool] = []

    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        return tools

    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[path.stem] = module
        spec.loader.exec_module(module)
    except Exception as e:
        import logging

        logging.warning(f"Failed to load {path}: {e}")
        return tools

    for name, obj in inspect.getmembers(module, inspect.isfunction):
        if name.startswith("_"):
            continue

        tool = _function_to_tool(obj, name)
        if tool:
            tools.append(tool)

    return tools


def _function_to_tool(func: Any, name: str) -> Any:
    """Convert a function to a LangChain tool."""
    from langchain_core.tools import BaseTool, StructuredTool

    if hasattr(func, "_tool_marker") and func._tool_marker:
        pass
    elif not _has_type_hints(func):
        return None

    description = getattr(func, "__doc__", None) or f"Tool: {name}"

    try:
        return StructuredTool.from_function(
            coroutine=func,
            name=name,
            description=description,
        )
    except Exception:
        return None


def _has_type_hints(func: Any) -> bool:
    """Check if function has type annotations on parameters."""
    sig = inspect.signature(func)
    annotations = getattr(func, "__annotations__", {})
    return bool(annotations) or any(p.annotation != inspect.Parameter.empty for p in sig.parameters.values())


def tool(func):
    """Decorator to mark a function as a tool.

    Usage:
        @tool
        async def my_tool(query: str) -> str:
            '''Description of what the tool does'''
            return "result"
    """
    func._tool_marker = True
    return func
