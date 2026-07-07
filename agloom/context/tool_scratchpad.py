"""Store full tool outputs off-thread; inject digests into the model transcript."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool

from ..src.logging_utils import get_logger

logger = get_logger(__name__)

_DIGEST_PREFIX = "[agloom:tool_digest"
_RECALL_TOOL_NAME = "recall_tool_artifact"


@dataclass
class ToolArtifact:
    ref_id: str
    tool_name: str
    content: str
    created_at: float = field(default_factory=time.time)
    tool_call_id: str | None = None


class ToolScratchpad:
    """Store for full tool payloads; optional LTS spill for durability."""

    _MAX_ARTIFACTS = 500
    _LTS_NS = ("context", "scratchpad")

    def __init__(self, *, store: Any = None, agent_key: str = "default") -> None:
        self._artifacts: dict[str, ToolArtifact] = {}
        self._store = store
        self._agent_key = agent_key

    def _lts_ns(self, ref_id: str) -> tuple:
        return self._LTS_NS + (self._agent_key, ref_id)

    def _spill_to_store(self, art: ToolArtifact) -> None:
        store = self._store
        if store is None:
            return
        put = getattr(store, "put", None)
        if not callable(put):
            return
        try:
            put(
                self._lts_ns(art.ref_id),
                "payload",
                {
                    "ref_id": art.ref_id,
                    "tool_name": art.tool_name,
                    "content": art.content,
                    "created_at": art.created_at,
                    "tool_call_id": art.tool_call_id,
                },
            )
        except Exception as exc:
            logger.debug(f"[tool_scratchpad] LTS spill failed ref={art.ref_id}: {exc!r}")

    def _load_from_store(self, ref_id: str) -> ToolArtifact | None:
        store = self._store
        if store is None:
            return None
        get = getattr(store, "get", None)
        if not callable(get):
            return None
        try:
            item = get(self._lts_ns(ref_id), "payload")
            if not item:
                return None
            val = item.value if hasattr(item, "value") else item
            if not isinstance(val, dict):
                return None
            art = ToolArtifact(
                ref_id=val.get("ref_id", ref_id),
                tool_name=val.get("tool_name", "tool"),
                content=str(val.get("content", "")),
                created_at=float(val.get("created_at", time.time())),
                tool_call_id=val.get("tool_call_id"),
            )
            self._artifacts[ref_id] = art
            return art
        except Exception:
            return None

    def store(
        self,
        tool_name: str,
        content: str,
        *,
        tool_call_id: str | None = None,
    ) -> ToolArtifact:
        ref_id = uuid.uuid4().hex[:12]
        art = ToolArtifact(
            ref_id=ref_id,
            tool_name=tool_name,
            content=content,
            tool_call_id=tool_call_id,
        )
        self._artifacts[ref_id] = art
        self._spill_to_store(art)
        if len(self._artifacts) > self._MAX_ARTIFACTS:
            oldest = min(self._artifacts.values(), key=lambda a: a.created_at)
            self._artifacts.pop(oldest.ref_id, None)
        return art

    def get(self, ref_id: str) -> ToolArtifact | None:
        rid = ref_id.strip()
        art = self._artifacts.get(rid)
        if art is not None:
            return art
        return self._load_from_store(rid)

    def recall_slice(self, ref_id: str, *, offset: int = 0, limit: int = 12_000) -> str:
        art = self.get(ref_id)
        if art is None:
            return f"No artifact found for ref_id={ref_id!r}."
        text = art.content
        if offset < 0:
            offset = 0
        if limit <= 0:
            limit = 12_000
        if offset >= len(text):
            return (
                f"[ref={ref_id} tool={art.tool_name}] offset {offset} past end "
                f"(total_chars={len(text)})."
            )
        chunk = text[offset : offset + limit]
        tail = offset + len(chunk)
        more = tail < len(text)
        header = (
            f"[ref={ref_id} tool={art.tool_name} chars={len(text)} "
            f"slice={offset}:{tail}{'+' if more else ''}]"
        )
        if more:
            return f"{header}\n{chunk}\n...(use offset={tail} for next slice)"
        return f"{header}\n{chunk}"

    def compact_stub(self, ref_id: str) -> str:
        art = self.get(ref_id)
        if art is None:
            return f"[compacted missing ref={ref_id}]"
        return (
            f"[compacted tool={art.tool_name} ref={ref_id} chars={len(art.content)} "
            f'— full text via recall_tool_artifact(ref_id="{ref_id}")]' 
        )


def serialize_tool_result(raw: Any) -> str:
    """Normalize tool return values to plain text for storage."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, ToolMessage):
        return str(raw.content or "")
    if isinstance(raw, dict):
        try:
            return json.dumps(raw, ensure_ascii=False, default=str)
        except Exception:
            return str(raw)
    return str(raw)


def build_tool_digest(
    *,
    ref_id: str,
    tool_name: str,
    full_text: str,
    preview_lines: int = 16,
) -> str:
    """Structured digest for the model; full payload remains in scratchpad."""
    lines = full_text.splitlines()
    preview = "\n".join(lines[:preview_lines])
    stats = f"chars={len(full_text)} lines={len(lines)}"
    more = len(lines) > preview_lines
    tail = f"\n...(stored; {stats})" if more else f"\n--- end preview ({stats}) ---"
    return (
        f"{_DIGEST_PREFIX} ref={ref_id} tool={tool_name} {stats}]\n"
        f'Full result stored off-thread. Use recall_tool_artifact(ref_id="{ref_id}") '
        f"for complete text (supports offset/limit slices).\n"
        f"--- preview ---\n{preview}"
        f"{tail}"
    )


def extract_ref_id_from_digest(text: str) -> str | None:
    if _DIGEST_PREFIX not in text:
        return None
    import re

    m = re.search(r"ref=([a-f0-9]{8,16})", text)
    return m.group(1) if m else None


def make_recall_tool_artifact(scratchpad: ToolScratchpad) -> StructuredTool:
    """Tool that retrieves full or sliced stored tool output by ref_id."""

    def recall_tool_artifact(ref_id: str, offset: int = 0, limit: int = 12000) -> str:
        """Retrieve stored tool output by ref_id from [agloom:tool_digest ...].

        Use offset/limit to page through very large artifacts without loading all at once.
        """
        return scratchpad.recall_slice(ref_id, offset=offset, limit=limit)

    return StructuredTool.from_function(
        name=_RECALL_TOOL_NAME,
        func=recall_tool_artifact,
        description=(
            "Retrieve the full stored output of a prior tool call. "
            "Pass ref_id from [agloom:tool_digest ref=...]. "
            "For large results, use offset/limit to page."
        ),
    )


def is_recall_tool_name(name: str) -> bool:
    return name == _RECALL_TOOL_NAME
