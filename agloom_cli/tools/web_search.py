"""Web search tool — search the web for up-to-date information."""

from __future__ import annotations

import os

from ..safety_limits import (
    WEB_SEARCH_ANSWER_MAX_CHARS,
    WEB_SEARCH_SNIPPET_MAX_CHARS,
    WEB_SEARCH_TOTAL_OUTPUT_MAX_CHARS,
)
from ..tool_arg_coerce import absent_to_none, coerce_int
from ..tool_loader import tool
from ..tool_result_envelope import render_incomplete
from .filesystem import _boolish

_WEB_HINTS = [
    "Do **not** assume snippets or answers are complete when ``complete=false``.",
    "Narrow the query, lower ``max_results``, or set ``include_raw_content=false`` if payloads are huge.",
]


@tool
async def web_search(
    query: str,
    max_results: int = 5,
    include_answer: bool = True,
    include_raw_content: bool = False,
) -> str:
    """Search the web for up-to-date information using Tavily API.

    Args:
        query: The search query
        max_results: Maximum number of results to return (default: 5)
        include_answer: Include AI-generated answer (default: True)
        include_raw_content: Include raw content from sources (default: False)

    Returns:
        Search results with relevant information
    """
    if not (query or "").strip():
        return "Error: query must be non-empty"
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return "Error: TAVILY_API_KEY not set. Get one at https://tavily.com/"

    mr_raw = absent_to_none(max_results)
    if mr_raw is None:
        mr_raw = 5
    max_res, merr = coerce_int(mr_raw, "max_results", min_value=1, max_value=10)
    if merr:
        return merr

    inc_ans = _boolish(include_answer, default=True)
    inc_raw = _boolish(include_raw_content, default=False)

    try:
        import httpx

        client = httpx.AsyncClient(timeout=30)
        try:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": max_res,
                    "include_answer": inc_ans,
                    "include_raw_content": inc_raw,
                    "include_images": False,
                },
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("results"):
                return f"No results found for: {query}"

            result_parts: list[str] = []
            truncated = False

            if data.get("answer"):
                ans = str(data["answer"])
                if len(ans) > WEB_SEARCH_ANSWER_MAX_CHARS:
                    ans = ans[:WEB_SEARCH_ANSWER_MAX_CHARS]
                    truncated = True
                result_parts.append(f"[Answer]\n{ans}\n")

            result_parts.append(f"[Results for '{query}']")
            for i, result in enumerate(data.get("results", []), 1):
                title = result.get("title", "No title")
                url = result.get("url", "")
                score = result.get("score", 0)
                try:
                    score = float(score)
                    score_str = f"{score:.2f}"
                except (TypeError, ValueError):
                    score_str = "N/A"
                content = str(result.get("content", ""))
                if len(content) > WEB_SEARCH_SNIPPET_MAX_CHARS:
                    content = content[:WEB_SEARCH_SNIPPET_MAX_CHARS]
                    truncated = True

                result_parts.append(f"\n{i}. {title}\n   URL: {url}\n   Score: {score_str}\n   {content}")

            out = "\n".join(result_parts)
            orig_len = len(out)
            if orig_len > WEB_SEARCH_TOTAL_OUTPUT_MAX_CHARS:
                out = out[:WEB_SEARCH_TOTAL_OUTPUT_MAX_CHARS]
                truncated = True

            if truncated:
                return render_incomplete(
                    kind="web_search_truncated",
                    metrics={
                        "answer_cap_chars": WEB_SEARCH_ANSWER_MAX_CHARS,
                        "snippet_cap_chars": WEB_SEARCH_SNIPPET_MAX_CHARS,
                        "total_cap_chars": WEB_SEARCH_TOTAL_OUTPUT_MAX_CHARS,
                        "returned_chars": len(out),
                    },
                    hints=_WEB_HINTS,
                    preview=out,
                    preview_title="--- partial web_search payload (trimmed to caps) ---",
                )
            return out

        finally:
            await client.aclose()

    except ImportError:
        return "Error: httpx not installed. Run: pip install httpx"
    except Exception as e:
        return f"Error: {e}"


@tool
async def search_web(query: str) -> str:
    """Simple web search - shorthand for web_search.

    Args:
        query: The search query

    Returns:
        Search results
    """
    return await web_search(query, max_results=5)


@tool
async def find_docs(query: str) -> str:
    """Search for documentation specifically.

    Args:
        query: Documentation search query

    Returns:
        Documentation results
    """
    return await web_search(f"{query} documentation", max_results=3)


@tool
async def search_github(query: str) -> str:
    """Search GitHub for repositories and code.

    Args:
        query: GitHub search query

    Returns:
        GitHub search results
    """
    return await web_search(f"site:github.com {query}", max_results=5)
