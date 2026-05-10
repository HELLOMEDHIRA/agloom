"""Minimal HTML → plain text for LLM-friendly URL previews (no extra dependencies)."""

from __future__ import annotations

import re
from html.parser import HTMLParser


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript"):
            self._skip_depth += 1
        elif t in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "title"):
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript") and self._skip_depth > 0:
            self._skip_depth -= 1
        elif t in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_readable_text(html: str, *, max_chars: int = 48_000) -> str:
    """Strip tags/scripts and collapse whitespace; cap length."""
    if not html or not html.strip():
        return ""
    try:
        p = _HTMLTextExtractor()
        p.feed(html)
        p.close()
        out = p.text()
    except Exception:
        out = re.sub(r"(?is)<script[^>]*>.*?</script>", "", html)
        out = re.sub(r"(?is)<style[^>]*>.*?</style>", "", out)
        out = re.sub(r"(?s)<[^>]+>", "\n", out)
        out = re.sub(r"\s+", " ", out).strip()
    if len(out) > max_chars:
        out = out[:max_chars] + "\n… truncated"
    return out
