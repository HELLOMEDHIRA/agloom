"""Store full tool outputs off-thread; inject digests into the model transcript."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, StructuredTool

from ..src.logging_utils import get_logger

from ..src.reserved_tools import TOOL_RECALL_TOOL_ARTIFACT

logger = get_logger(__name__)

_DIGEST_PREFIX = "[agloom:tool_digest"
_RECALL_TOOL_NAME = TOOL_RECALL_TOOL_ARTIFACT

# Maximum chars any ToolMessage may occupy on the wire after digest/stub.
MAX_TOOL_WIRE_CHARS = 12_000
MONOLITHIC_LINE_THRESHOLD = 2048
DEFAULT_DIGEST_PREVIEW_LINES = 16


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
            f'— full text via {TOOL_RECALL_TOOL_ARTIFACT}(ref_id="{ref_id}")]'
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


def _detect_payload_format(full_text: str, lines: list[str]) -> Literal["json", "ndjson", "text"]:
    stripped = full_text.strip()
    if not stripped:
        return "text"
    if len(lines) > 1:
        json_lines = 0
        for line in lines[:20]:
            s = line.strip()
            if not s:
                continue
            try:
                json.loads(s)
                json_lines += 1
            except json.JSONDecodeError:
                return "text"
        if json_lines >= 2:
            return "ndjson"
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            json.loads(stripped)
            return "json"
        except json.JSONDecodeError:
            pass
    return "text"


def _json_envelope_metadata(full_text: str) -> str:
    stripped = full_text.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return ""
    if isinstance(parsed, dict):
        keys = list(parsed.keys())[:24]
        return f"keys={keys}"
    if isinstance(parsed, list):
        return f"array_len={len(parsed)}"
    return f"type={type(parsed).__name__}"


def is_monolithic_payload(
    full_text: str,
    *,
    monolithic_line_threshold: int = MONOLITHIC_LINE_THRESHOLD,
) -> bool:
    lines = full_text.splitlines()
    if len(lines) <= 1 and len(full_text) > monolithic_line_threshold:
        return True
    return any(len(line) > monolithic_line_threshold for line in lines)


def _digest_header(*, ref_id: str, tool_name: str, stats: str) -> str:
    return (
        f"{_DIGEST_PREFIX} ref={ref_id} tool={tool_name} {stats}]\n"
        f'Full result stored off-thread. Use {TOOL_RECALL_TOOL_ARTIFACT}(ref_id="{ref_id}", '
        f"offset=0, limit=12000) for complete text (supports offset/limit slices)."
    )


def build_tool_digest_metadata_only(
    *,
    ref_id: str,
    tool_name: str,
    full_text: str,
) -> str:
    lines = full_text.splitlines()
    stats = f"chars={len(full_text)} lines={len(lines)}"
    fmt = _detect_payload_format(full_text, lines)
    envelope = _json_envelope_metadata(full_text) if fmt in ("json", "ndjson") else ""
    meta = f"format={fmt}"
    if envelope:
        meta = f"{meta} {envelope}"
    return f"{_digest_header(ref_id=ref_id, tool_name=tool_name, stats=stats)}\n{meta}"


def build_tool_digest(
    *,
    ref_id: str,
    tool_name: str,
    full_text: str,
    preview_lines: int = DEFAULT_DIGEST_PREVIEW_LINES,
    monolithic_line_threshold: int = MONOLITHIC_LINE_THRESHOLD,
    max_wire_chars: int | None = MAX_TOOL_WIRE_CHARS,
) -> str:
    """Structured digest for the model; full payload remains in scratchpad."""
    if is_monolithic_payload(full_text, monolithic_line_threshold=monolithic_line_threshold):
        digest = build_tool_digest_metadata_only(ref_id=ref_id, tool_name=tool_name, full_text=full_text)
        return bound_digest_to_wire(digest, ref_id=ref_id, tool_name=tool_name, full_text=full_text, max_wire_chars=max_wire_chars)

    lines = full_text.splitlines()
    stats = f"chars={len(full_text)} lines={len(lines)}"
    header = _digest_header(ref_id=ref_id, tool_name=tool_name, stats=stats)
    preview = "\n".join(lines[:preview_lines])
    more = len(lines) > preview_lines
    tail = f"\n...(stored; {stats})" if more else f"\n--- end preview ({stats}) ---"
    digest = f"{header}\n--- preview ---\n{preview}{tail}"

    if max_wire_chars is not None and len(digest) > max_wire_chars:
        reduced_lines = preview_lines
        while reduced_lines > 1 and len(digest) > max_wire_chars:
            reduced_lines -= 1
            preview = "\n".join(lines[:reduced_lines])
            more = len(lines) > reduced_lines
            tail = f"\n...(stored; {stats})" if more else f"\n--- end preview ({stats}) ---"
            digest = f"{header}\n--- preview ---\n{preview}{tail}"
        if len(digest) > max_wire_chars:
            digest = build_tool_digest_metadata_only(ref_id=ref_id, tool_name=tool_name, full_text=full_text)

    return bound_digest_to_wire(digest, ref_id=ref_id, tool_name=tool_name, full_text=full_text, max_wire_chars=max_wire_chars)


def bound_digest_to_wire(
    digest: str,
    *,
    ref_id: str,
    tool_name: str,
    full_text: str,
    max_wire_chars: int | None,
) -> str:
    if max_wire_chars is None or len(digest) <= max_wire_chars:
        return digest
    return build_tool_digest_metadata_only(ref_id=ref_id, tool_name=tool_name, full_text=full_text)


async def build_tool_digest_async(
    *,
    ref_id: str,
    tool_name: str,
    full_text: str,
    summarizer_model: Any | None = None,
    preview_lines: int = DEFAULT_DIGEST_PREVIEW_LINES,
    monolithic_line_threshold: int = MONOLITHIC_LINE_THRESHOLD,
    max_wire_chars: int | None = MAX_TOOL_WIRE_CHARS,
    digest_preview_token_budget: int | None = None,
) -> str:
    """Async digest with optional summarization when preview still exceeds wire budget."""
    digest = build_tool_digest(
        ref_id=ref_id,
        tool_name=tool_name,
        full_text=full_text,
        preview_lines=preview_lines,
        monolithic_line_threshold=monolithic_line_threshold,
        max_wire_chars=None,
    )
    if max_wire_chars is not None and len(digest) <= max_wire_chars:
        return digest
    if summarizer_model is not None and not is_monolithic_payload(
        full_text, monolithic_line_threshold=monolithic_line_threshold
    ):
        from .summarize import summarize_text_for_budget

        if "--- preview ---" in digest:
            head, _, preview_block = digest.partition("--- preview ---\n")
            summarized = await summarize_text_for_budget(preview_block, summarizer_model=summarizer_model)
            digest = f"{head}--- preview ---\n{summarized}"
            if max_wire_chars is None or len(digest) <= max_wire_chars:
                return digest
    return build_tool_digest_metadata_only(ref_id=ref_id, tool_name=tool_name, full_text=full_text)


def extract_ref_id_from_digest(text: str) -> str | None:
    if _DIGEST_PREFIX not in text:
        return None
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


def attach_tool_scratchpad(
    tools: list[BaseTool],
    *,
    store: Any = None,
    agent_key: str,
    existing_pad: ToolScratchpad | None = None,
) -> tuple[ToolScratchpad | None, list[BaseTool]]:
    """Wire scratchpad + recall_tool_artifact when the agent has tools."""
    if not tools:
        return existing_pad, list(tools)
    pad = existing_pad or ToolScratchpad(store=store, agent_key=agent_key)
    out = list(tools)
    if not any(is_recall_tool_name(getattr(t, "name", "") or "") for t in out):
        out = [*out, make_recall_tool_artifact(pad)]
    return pad, out


def ensure_tool_scratchpad_config(config: dict[str, Any]) -> bool:
    """Bootstrap scratchpad on agent config when tools exist but pad was not wired. Returns True if changed."""
    if config.get("_tool_scratchpad") is not None:
        return False
    tools = list(config.get("tools") or [])
    if not tools:
        return False
    agent_name = str(config.get("name") or "Agent")
    store = config.get("store")
    pad, new_tools = attach_tool_scratchpad(tools, store=store, agent_key=agent_name)
    config["_tool_scratchpad"] = pad
    config["tool_scratchpad"] = pad is not None
    config["tools"] = new_tools
    if not config.get("tool_digest_min_chars"):
        from .plane import compute_context_budget

        llm = config.get("llm")
        window = config.get("context_window_tokens")
        budget = compute_context_budget(llm, context_window_tokens=window)
        config["tool_digest_min_chars"] = budget.digest_min_chars
    return True
