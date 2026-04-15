"""Web search tool — search the web for up-to-date information."""

from __future__ import annotations

import os

from ..tool_loader import tool


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
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return "Error: TAVILY_API_KEY not set. Get one at https://tavily.com/"

    try:
        import httpx

        client = httpx.AsyncClient(timeout=30)
        try:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": include_answer,
                    "include_raw_content": include_raw_content,
                    "include_images": False,
                },
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("results"):
                return f"No results found for: {query}"

            result_parts = []

            if data.get("answer"):
                result_parts.append(f"[Answer]\n{data['answer']}\n")

            result_parts.append(f"[Results for '{query}']")
            for i, result in enumerate(data.get("results", []), 1):
                title = result.get("title", "No title")
                url = result.get("url", "")
                score = result.get("score", 0)
                content = result.get("content", "")[:300]

                result_parts.append(f"\n{i}. {title}\n   URL: {url}\n   Score: {score:.2f}\n   {content}...")

            return "\n".join(result_parts)

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
