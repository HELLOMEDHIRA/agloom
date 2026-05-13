"""HTTP fetch and optional web search (provider via ``AGLOOM_SEARCH_PROVIDER``)."""

from __future__ import annotations

import os
from typing import Any

from langchain_core.tools import tool

from .html_extract import html_to_readable_text


def _try_trafilatura_extract(html: str, *, url: str | None) -> str | None:
    """Optional readability extraction; ``None`` → caller uses :func:`html_to_readable_text`."""
    import importlib

    try:
        trafilatura = importlib.import_module("trafilatura")
    except ImportError:
        return None
    try:
        out = trafilatura.extract(html, url=url or None)
        if isinstance(out, str) and out.strip():
            return out.strip()
    except Exception:
        return None
    return None


def _looks_like_html(body: bytes) -> bool:
    head = body[:512].lstrip().lower()
    return head.startswith(b"<")


async def _http_get_text_async(
    *,
    url: str,
    max_bytes: int,
    allow_network: bool,
    extract_readable_text: bool,
    prefer_trafilatura: bool = False,
) -> str:
    if not allow_network:
        return "fetch_url: network tools disabled by runtime configuration"
    raw = (url or "").strip()
    if not raw:
        return "fetch_url: empty url"
    cap = max(1024, min(max_bytes, 2_000_000))
    try:
        import httpx
    except ImportError as exc:
        return f"fetch_url: httpx not installed ({exc})"
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(raw)
            resp.raise_for_status()
            body = resp.content[:cap]
            status = resp.status_code
            ctype = resp.headers.get("content-type", "")
    except Exception as exc:
        return f"fetch_url: {exc}"
    text = body.decode("utf-8", errors="replace")
    if extract_readable_text and ("html" in ctype.lower() or _looks_like_html(body)):
        if prefer_trafilatura:
            alt = _try_trafilatura_extract(text, url=raw)
            text = alt if alt is not None else html_to_readable_text(text)
        else:
            text = html_to_readable_text(text)
    if len(text) > 24_000:
        text = text[:24_000] + "\n… truncated"
    return f"status={status}\n{text}"


def make_web_tools(*, allow_network: bool) -> list:
    @tool
    async def fetch_url(url: str, max_bytes: int = 512_000, extract_readable_text: bool = True) -> str:
        """HTTP GET *url*. When ``extract_readable_text=True`` (default), HTML bodies are stripped to plain text."""
        return await _http_get_text_async(
            url=url,
            max_bytes=max_bytes,
            allow_network=allow_network,
            extract_readable_text=extract_readable_text,
        )

    @tool
    async def read_url_markdown(url: str, max_bytes: int = 512_000) -> str:
        """Fetch a URL and return readability-style plain text.

        Uses ``trafilatura`` when installed (``pip install 'agloom[readability]'``); otherwise the
        built-in HTML stripper.
        """
        return await _http_get_text_async(
            url=url,
            max_bytes=max_bytes,
            allow_network=allow_network,
            extract_readable_text=True,
            prefer_trafilatura=True,
        )

    @tool
    async def web_search(query: str, max_results: int = 5) -> str:
        """Search the web when ``AGLOOM_SEARCH_PROVIDER`` is set (``searxng``, ``tavily``, ``brave``)."""
        if not allow_network:
            return "web_search: network tools disabled by runtime configuration"
        q = (query or "").strip()
        if not q:
            return "web_search: empty query"
        provider = (os.environ.get("AGLOOM_SEARCH_PROVIDER") or "").strip().lower()
        if not provider:
            return (
                "web_search: set AGLOOM_SEARCH_PROVIDER "
                "(searxng | tavily | brave — see docs)."
            )
        n = max(1, min(max_results, 10))

        try:
            import httpx
        except ImportError as exc:
            return f"web_search: httpx not installed ({exc})"

        if provider == "searxng":
            base = (os.environ.get("AGLOOM_SEARXNG_URL") or "").strip().rstrip("/")
            if not base:
                return "web_search (searxng): set AGLOOM_SEARXNG_URL to your instance base (e.g. https://search.example)"
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.get(f"{base}/search", params={"q": q, "format": "json"})
                    r.raise_for_status()
                    data: Any = r.json()
            except Exception as exc:
                return f"web_search (searxng): {exc}"
            results = data.get("results") if isinstance(data, dict) else None
            if not isinstance(results, list):
                return "web_search (searxng): unexpected JSON (is JSON format enabled on the instance?)"
            lines = []
            for item in results[:n]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "")
                href = str(item.get("url") or "")
                snippet = str(item.get("content") or item.get("snippet") or "")
                lines.append(f"- {title}\n  {href}\n  {snippet[:400]}")
            return "\n".join(lines) if lines else "web_search: no results"

        if provider == "tavily":
            key = os.environ.get("TAVILY_API_KEY", "").strip()
            if not key:
                return "web_search: TAVILY_API_KEY is not set"
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.post(
                        "https://api.tavily.com/search",
                        json={"api_key": key, "query": q, "max_results": n},
                    )
                    r.raise_for_status()
                    data: Any = r.json()
            except Exception as exc:
                return f"web_search (tavily): {exc}"
            results = data.get("results") if isinstance(data, dict) else None
            if not isinstance(results, list):
                return "web_search (tavily): unexpected response shape"
            lines = []
            for item in results[:n]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "")
                href = str(item.get("url") or "")
                snippet = str(item.get("content") or item.get("snippet") or "")
                lines.append(f"- {title}\n  {href}\n  {snippet[:400]}")
            return "\n".join(lines) if lines else "web_search: no results"

        if provider == "brave":
            key = os.environ.get("BRAVE_API_KEY", "").strip()
            if not key:
                return "web_search: BRAVE_API_KEY is not set"
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.get(
                        "https://api.search.brave.com/res/v1/web/search",
                        params={"q": q, "count": n},
                        headers={"X-Subscription-Token": key},
                    )
                    r.raise_for_status()
                    data = r.json()
            except Exception as exc:
                return f"web_search (brave): {exc}"
            web = data.get("web") if isinstance(data, dict) else None
            results = web.get("results") if isinstance(web, dict) else None
            if not isinstance(results, list):
                return "web_search (brave): unexpected response shape"
            lines = []
            for item in results[:n]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "")
                href = str(item.get("url") or "")
                desc = str(item.get("description") or "")
                lines.append(f"- {title}\n  {href}\n  {desc[:400]}")
            return "\n".join(lines) if lines else "web_search: no results"

        return f"web_search: unknown AGLOOM_SEARCH_PROVIDER={provider!r}"

    return [fetch_url, read_url_markdown, web_search]
