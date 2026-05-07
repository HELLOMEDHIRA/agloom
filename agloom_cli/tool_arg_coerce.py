"""Normalize tool arguments when models send wrong JSON types (str for int, stringified dicts, etc.)."""

from __future__ import annotations

import json
from typing import Any

_MAX_JSON_STRING_CHARS = 2_000_000


def absent_to_none(value: Any) -> Any:
    """Treat None and blank strings as absent (for optional fields)."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def coerce_int(
    value: Any,
    field: str,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
) -> tuple[int | None, str | None]:
    """Parse a required integer. Returns ``(n, None)`` or ``(None, error_message)``."""
    v = absent_to_none(value)
    if v is None:
        return None, f"Error: {field} is required and cannot be empty."

    if isinstance(v, bool):
        return None, f"Error: {field} must be an integer, not a boolean."
    if isinstance(v, int):
        n = v
    elif isinstance(v, float):
        if not v.is_integer():
            return None, f"Error: {field} must be a whole number, got {v!r}."
        n = int(v)
    elif isinstance(v, str):
        s = v.strip().lower()
        if s in ("", "null", "none"):
            return None, f"Error: {field} is required and cannot be empty."
        try:
            n = int(s, 10)
        except ValueError:
            return None, f"Error: {field} must be an integer, got {value!r}."
    else:
        return None, f"Error: {field} must be an integer, got {type(value).__name__}."

    if min_value is not None and n < min_value:
        return None, f"Error: {field} must be >= {min_value}, got {n}."
    if max_value is not None and n > max_value:
        return None, f"Error: {field} must be <= {max_value}, got {n}."
    return n, None


def coerce_optional_int(
    value: Any,
    field: str,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
) -> tuple[int | None, str | None]:
    """Like :func:`coerce_int` but absent values → ``(None, None)``."""
    v = absent_to_none(value)
    if v is None:
        return None, None
    return coerce_int(v, field, min_value=min_value, max_value=max_value)


def coerce_json_object(
    value: Any,
    field: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """``dict`` or JSON object string → ``dict``. Absent → ``None``."""
    v = absent_to_none(value)
    if v is None:
        return None, None
    if isinstance(v, dict):
        return v, None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None, None
        if len(s) > _MAX_JSON_STRING_CHARS:
            return None, f"Error: {field} JSON string exceeds maximum length."
        try:
            obj = json.loads(s)
        except json.JSONDecodeError as e:
            return None, f"Error: {field} must be a JSON object (dict) or a valid JSON object string: {e}"
        if not isinstance(obj, dict):
            return None, (
                f"Error: {field} must be a JSON object at the top level (dict), got {type(obj).__name__}."
            )
        return obj, None
    return None, f"Error: {field} must be a dict or JSON object string, got {type(v).__name__}."


def coerce_headers(value: Any, field: str = "headers") -> tuple[dict[str, str] | None, str | None]:
    """HTTP headers: JSON object with stringifiable values (httpx expects str values)."""
    raw, err = coerce_json_object(value, field)
    if err:
        return None, err
    if raw is None:
        return None, None
    out: dict[str, str] = {}
    for k, v in raw.items():
        if v is None:
            out[str(k)] = ""
        elif isinstance(v, str):
            out[str(k)] = v
        elif isinstance(v, (bool, int, float)):
            out[str(k)] = str(v).lower() if isinstance(v, bool) else str(v)
        else:
            try:
                out[str(k)] = json.dumps(v, separators=(",", ":"))
            except (TypeError, ValueError):
                out[str(k)] = str(v)
    return out, None


def coerce_query_params(value: Any, field: str = "params") -> tuple[dict[str, Any] | None, str | None]:
    """URL query parameters: ``dict`` or JSON object string (values stay JSON-serializable)."""
    return coerce_json_object(value, field)


def coerce_http_body(value: Any, field: str = "body") -> tuple[Any, str | None]:
    """Request body: ``dict`` / ``list`` (JSON), raw ``str``, or JSON string → parsed object.

    Returns a value suitable for httpx: ``dict``/``list`` → ``json=``, ``str`` → ``content=``.
    """
    v = absent_to_none(value)
    if v is None:
        return None, None
    if isinstance(v, dict):
        return v, None
    if isinstance(v, list):
        return v, None
    if isinstance(v, str):
        s = v
        if not s.strip():
            return None, None
        if s.lstrip()[:1] in "{[":
            if len(s) > _MAX_JSON_STRING_CHARS:
                return None, f"Error: {field} JSON string exceeds maximum length."
            try:
                parsed = json.loads(s)
            except json.JSONDecodeError as e:
                return None, f"Error: {field} looks like JSON but failed to parse: {e}"
            if isinstance(parsed, (dict, list)):
                return parsed, None
            return json.dumps(parsed), None
        return s, None
    if isinstance(v, (bool, int, float)):
        return json.dumps(v), None
    return None, f"Error: {field} has unsupported type {type(v).__name__}."


def coerce_env_vars(value: Any, field: str = "env") -> tuple[dict[str, str] | None, str | None]:
    """Environment overrides: same as headers (string values only)."""
    return coerce_headers(value, field)
