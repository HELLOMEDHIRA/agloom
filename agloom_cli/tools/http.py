"""HTTP requests tool — make HTTP calls to APIs and external services."""

from __future__ import annotations

import json
from typing import Any

import httpx

from ..safety_limits import (
    FETCH_JSON_INCOMPLETE_PREVIEW_CHARS,
    HTTP_INCOMPLETE_PREVIEW_BYTES,
    HTTP_INCOMPLETE_PREVIEW_CHARS,
    HTTP_MAX_BODY_CHARS,
    HTTP_MAX_RESPONSE_BYTES,
)
from ..tool_result_envelope import render_incomplete
from ..tool_loader import tool

_HTTP_RECOVERY_HINTS = [
    "Do **not** treat any preview as the full response — check ``complete=false`` in the agloom block above.",
    "Retry with pagination, smaller filters, ``Range: bytes=...``, or download to a file and use read_file(offset/limit).",
]


def _redact_header(name: str, value: str) -> str:
    n = name.lower()
    if n in {"authorization", "cookie", "set-cookie"}:
        return "[REDACTED]"
    if "token" in n or "secret" in n:
        return "[REDACTED]"
    return value


@tool
async def http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | str | None = None,
    timeout: int = 30,
) -> str:
    """Make an HTTP request to an API or external service.

    Args:
        url: The URL to request
        method: HTTP method (GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS)
        headers: Optional HTTP headers
        params: Optional URL query parameters
        body: Optional request body (dict for JSON, or string)
        timeout: Request timeout in seconds (default: 30)

    Returns:
        Formatted response with status, headers, and body
    """
    if not (url or "").strip():
        return "Error: url must be non-empty"
    try:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

        try:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=headers,
                params=params,
                json=body if isinstance(body, dict) else None,
                content=body if isinstance(body, str) else None,
            )

            result_parts = [
                f"[Status: {response.status_code} {response.reason_phrase}]",
            ]

            if response.headers:
                result_parts.append("\n[Headers]")
                for k, v in response.headers.items():
                    result_parts.append(f"  {k}: {_redact_header(k, v)}")

            if response.content:
                result_parts.append("\n[Body]")
                nbytes = len(response.content)
                if nbytes > HTTP_MAX_RESPONSE_BYTES:
                    prv_b = response.content[:HTTP_INCOMPLETE_PREVIEW_BYTES]
                    prv = prv_b.decode("utf-8", errors="replace")
                    result_parts.append(
                        render_incomplete(
                            kind="http_body_bytes_cap",
                            metrics={
                                "bytes_total": nbytes,
                                "bytes_cap": HTTP_MAX_RESPONSE_BYTES,
                                "preview_bytes": len(prv_b),
                            },
                            hints=_HTTP_RECOVERY_HINTS,
                            preview=prv,
                        )
                    )
                else:
                    text = response.content.decode("utf-8", errors="replace")
                    try:
                        parsed = json.loads(text)
                        formatted = json.dumps(parsed, indent=2)
                        if len(formatted) > HTTP_MAX_BODY_CHARS:
                            prv = formatted[:HTTP_INCOMPLETE_PREVIEW_CHARS]
                            result_parts.append(
                                render_incomplete(
                                    kind="http_body_chars_cap",
                                    metrics={
                                        "chars_total": len(formatted),
                                        "chars_cap": HTTP_MAX_BODY_CHARS,
                                        "preview_chars": len(prv),
                                    },
                                    hints=_HTTP_RECOVERY_HINTS,
                                    preview=prv,
                                )
                            )
                        else:
                            result_parts.append(formatted)
                    except json.JSONDecodeError:
                        if len(text) > HTTP_MAX_BODY_CHARS:
                            prv = text[:HTTP_INCOMPLETE_PREVIEW_CHARS]
                            result_parts.append(
                                render_incomplete(
                                    kind="http_body_chars_cap",
                                    metrics={
                                        "chars_total": len(text),
                                        "chars_cap": HTTP_MAX_BODY_CHARS,
                                        "preview_chars": len(prv),
                                    },
                                    hints=_HTTP_RECOVERY_HINTS,
                                    preview=prv,
                                )
                            )
                        else:
                            result_parts.append(text)

            return "\n".join(result_parts)

        finally:
            await client.aclose()

    except httpx.TimeoutException:
        return f"Error: Request timed out after {timeout} seconds"
    except httpx.ConnectError as e:
        return f"Error: Could not connect to {url}: {e}"
    except httpx.HTTPError as e:
        return f"Error: HTTP error: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool
async def http_get(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> str:
    """Make a GET request (shorthand for http_request).

    Args:
        url: The URL to GET
        params: Optional query parameters
        headers: Optional HTTP headers

    Returns:
        Response from the server
    """
    return await http_request(url, method="GET", params=params, headers=headers)


@tool
async def http_post(url: str, body: dict[str, Any] | str | None = None, headers: dict[str, str] | None = None) -> str:
    """Make a POST request (shorthand for http_request).

    Args:
        url: The URL to POST to
        body: Request body (dict for JSON, or string)
        headers: Optional HTTP headers

    Returns:
        Response from the server
    """
    return await http_request(url, method="POST", body=body, headers=headers)


@tool
async def http_put(url: str, body: dict[str, Any] | str | None = None, headers: dict[str, str] | None = None) -> str:
    """Make a PUT request (shorthand for http_request).

    Args:
        url: The URL to PUT to
        body: Request body (dict for JSON, or string)
        headers: Optional HTTP headers

    Returns:
        Response from the server
    """
    return await http_request(url, method="PUT", body=body, headers=headers)


@tool
async def http_delete(url: str, headers: dict[str, str] | None = None) -> str:
    """Make a DELETE request (shorthand for http_request).

    Args:
        url: The URL to DELETE
        headers: Optional HTTP headers

    Returns:
        Response from the server
    """
    return await http_request(url, method="DELETE", headers=headers)


@tool
async def http_head(url: str, headers: dict[str, str] | None = None) -> str:
    """Make a HEAD request to get headers only.

    Args:
        url: The URL to HEAD
        headers: Optional HTTP headers

    Returns:
        Response headers from the server
    """
    return await http_request(url, method="HEAD", headers=headers)


@tool
async def fetch_json(url: str, params: dict[str, Any] | None = None, key: str | None = None) -> str:
    """Fetch JSON from a URL and optionally extract a specific key.

    Args:
        url: The URL to fetch JSON from
        params: Optional query parameters
        key: Optional key to extract from JSON response

    Returns:
        JSON data or the specific key value
    """
    if not (url or "").strip():
        return "Error: url must be non-empty"
    try:
        client = httpx.AsyncClient(timeout=30, follow_redirects=True)
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            nbytes = len(response.content)
            if nbytes > HTTP_MAX_RESPONSE_BYTES:
                prv_b = response.content[:HTTP_INCOMPLETE_PREVIEW_BYTES]
                prv = prv_b.decode("utf-8", errors="replace")
                return render_incomplete(
                    kind="fetch_json_response_bytes_cap",
                    metrics={
                        "bytes_total": nbytes,
                        "bytes_cap": HTTP_MAX_RESPONSE_BYTES,
                        "preview_bytes": len(prv_b),
                    },
                    hints=_HTTP_RECOVERY_HINTS,
                    preview=prv,
                )
            data = response.json()

            if key:
                keys = key.split(".")
                for k in keys:
                    if isinstance(data, dict):
                        data = data.get(k, f"Key '{k}' not found")
                    else:
                        return f"Key '{key}' not found in non-dict response"
                out = str(data) if not isinstance(data, (dict, list)) else json.dumps(data, indent=2)
            else:
                out = json.dumps(data, indent=2)
            if len(out) > HTTP_MAX_BODY_CHARS:
                prv = out[:FETCH_JSON_INCOMPLETE_PREVIEW_CHARS]
                return render_incomplete(
                    kind="fetch_json_serialized_chars_cap",
                    metrics={
                        "chars_total": len(out),
                        "chars_cap": HTTP_MAX_BODY_CHARS,
                        "preview_chars": len(prv),
                    },
                    hints=_HTTP_RECOVERY_HINTS,
                    preview=prv,
                )
            return out
        finally:
            await client.aclose()

    except Exception as e:
        return f"Error fetching JSON: {e}"
