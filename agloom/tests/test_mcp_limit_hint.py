"""MCP tool description limit hints at bind time."""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agloom.src.mcp_support import _AGLOOM_LIMIT_HINT, _tool_has_limit_param, _with_agloom_limit_hint


class _LogsArgs(BaseModel):
    limit: int = Field(default=50, description="Maximum rows to return")
    service: str = Field(default="", description="Service filter")


class _QueryArgs(BaseModel):
    query: str = Field(description="Search query")


def _fetch_logs(limit: int = 50, service: str = "") -> str:
    return f"ok limit={limit} service={service}"


def _search(query: str) -> str:
    return query


def test_tool_has_limit_param_detects_schema_fields() -> None:
    with_limit = StructuredTool.from_function(
        _fetch_logs,
        name="fetch_logs",
        description="Fetch logs",
        args_schema=_LogsArgs,
    )
    without_limit = StructuredTool.from_function(
        _search,
        name="search",
        description="Search",
        args_schema=_QueryArgs,
    )
    assert _tool_has_limit_param(with_limit) is True
    assert _tool_has_limit_param(without_limit) is False


def test_with_agloom_limit_hint_appends_once() -> None:
    tool = StructuredTool.from_function(
        _fetch_logs,
        name="fetch_logs",
        description="Fetch correlated logs",
        args_schema=_LogsArgs,
    )
    hinted = _with_agloom_limit_hint(tool)
    assert _AGLOOM_LIMIT_HINT.strip() in (hinted.description or "")
    assert hinted.description.count("Agloom: pass limit") == 1
    again = _with_agloom_limit_hint(hinted)
    assert again.description == hinted.description


def test_with_agloom_limit_hint_skips_tools_without_limit_param() -> None:
    tool = StructuredTool.from_function(
        _search,
        name="search",
        description="Plain search",
        args_schema=_QueryArgs,
    )
    hinted = _with_agloom_limit_hint(tool)
    assert hinted.description == "Plain search"
    assert "Agloom: pass limit" not in (hinted.description or "")
