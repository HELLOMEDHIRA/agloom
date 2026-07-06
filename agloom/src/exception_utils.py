"""Shared helpers for surfacing root causes from nested / grouped exceptions."""

from __future__ import annotations


def unwrap_exception(exc: BaseException) -> BaseException:
    """Return the deepest useful leaf from ``ExceptionGroup`` / cause chains."""
    current = exc
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        group_types: tuple[type, ...] = (ExceptionGroup, BaseExceptionGroup)
        if isinstance(current, group_types) and getattr(current, "exceptions", None):
            current = current.exceptions[0]
            continue
        cause = current.__cause__ or current.__context__
        if cause is not None and cause is not current:
            current = cause
            continue
        break
    return current


def _http_error_detail(exc: BaseException, *, max_len: int = 500) -> str:
    """Append response body from httpx ``HTTPStatusError`` when present."""
    response = getattr(exc, "response", None)
    if response is None:
        return ""
    chunks: list[str] = []
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        chunks.append(f"status={status}")
    url = getattr(response, "url", None)
    if url is not None:
        chunks.append(f"url={url}")
    text = ""
    for attr in ("text", "content"):
        raw = getattr(response, attr, None)
        if raw is None:
            continue
        if isinstance(raw, bytes):
            text = raw.decode("utf-8", errors="replace").strip()
        elif isinstance(raw, str):
            text = raw.strip()
        if text:
            break
    if not text:
        json_fn = getattr(response, "json", None)
        if callable(json_fn):
            try:
                payload = json_fn()
                text = str(payload).strip()
            except Exception:
                text = ""
    if text:
        if len(text) > max_len:
            text = text[: max_len - 3] + "..."
        chunks.append(f"body={text}")
    return "; ".join(chunks)


def format_exception_message(exc: BaseException, *, include_type: bool = True) -> str:
    """Human-readable message with ``ExceptionGroup`` / ``TaskGroup`` wrappers removed."""
    root = unwrap_exception(exc)
    msg = str(root).strip() or repr(root)
    http_detail = _http_error_detail(root)
    if http_detail and http_detail not in msg:
        msg = f"{msg} ({http_detail})"
    if not include_type:
        return msg
    type_name = type(root).__name__
    if msg.startswith(f"{type_name}:") or msg.startswith(f"{type_name}("):
        return msg
    return f"{type_name}: {msg}"
