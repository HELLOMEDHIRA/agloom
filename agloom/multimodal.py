"""Stage ``command.invoke`` attachments and build user-turn content for the agent + AGP wire."""

from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path
from typing import Any

from agloom.protocol.commands import CommandInvoke

MAX_ATTACHMENTS = 8
MAX_BYTES_PER_FILE = 5 * 1024 * 1024


def model_id_supports_vision(model_id: str | None) -> bool:
    if not model_id:
        return False
    m = model_id.lower()
    if any(x in m for x in ("gpt-3.5", "gpt-35", "text-davinci")):
        return False
    if any(
        x in m
        for x in (
            "gpt-4o",
            "gpt-4-turbo",
            "gpt-4-vision",
            "claude-3",
            "claude-sonnet-4",
            "gemini",
            "vision",
            "llama-3.2",
            "llama3.2",
            "qwen-vl",
            "pixtral",
        )
    ):
        return True
    return False


def _safe_name(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", (name or "file").strip())
    return (s[:120] or "file")


def text_from_user_turn(user_turn: str | list[dict[str, Any]]) -> str:
    if isinstance(user_turn, str):
        return user_turn
    parts: list[str] = []
    for block in user_turn:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            t = block.get("text")
            if isinstance(t, str):
                parts.append(t)
    return "\n".join(parts) if parts else str(user_turn)


def merge_context_into_user_turn(augmented_text: str, original_user: Any) -> str | list[dict[str, Any]]:
    """Classifier/memory use plain text; restore vision ``image_url`` blocks for the pattern handler."""
    if isinstance(original_user, dict):
        return augmented_text
    if isinstance(original_user, str):
        return augmented_text
    images: list[dict[str, Any]] = []
    for b in original_user:
        if isinstance(b, dict) and b.get("type") == "image_url":
            images.append(b)
    if not images:
        return augmented_text
    return [{"type": "text", "text": augmented_text}, *images]


def guess_model_id(agent: Any) -> str | None:
    llm_obj = getattr(agent, "config", {}).get("llm")
    if llm_obj is None:
        return None
    mid = getattr(llm_obj, "model_name", None) or getattr(llm_obj, "model", None)
    return str(mid) if mid else type(llm_obj).__name__


def prepare_invoke_command(
    cmd: CommandInvoke,
    *,
    agent: Any,
    thread: str,
    working_dir: Path,
) -> tuple[Any, list[dict[str, Any]]]:
    """Resolve ``command.invoke`` into ``(prompt_for_agent, attachment_summaries)``."""
    model_id = guess_model_id(agent)
    atts = getattr(cmd.data, "attachments", None) or []
    return prepare_invoke_attachments(
        prompt=cmd.data.prompt,
        attachments=atts,
        thread=thread,
        working_dir=working_dir,
        model_id=model_id,
    )


def prepare_invoke_attachments(
    *,
    prompt: str,
    attachments: list[Any],
    thread: str,
    working_dir: Path,
    model_id: str | None,
) -> tuple[str | list[dict[str, Any]], list[dict[str, Any]]]:
    """Decode attachments, stage under ``working_dir/.agloom/attachments/<thread>/``.

    Returns ``(user_turn, wire_summaries)`` where ``user_turn`` is either a plain string
    (non-vision or non-image) or an OpenAI-style multimodal ``content`` list for the first
    HumanMessage. ``wire_summaries`` are small dicts for ``message.user`` on the wire.
    """
    if not attachments:
        return prompt, []

    root = (working_dir / ".agloom" / "attachments" / _safe_name(thread)).resolve()
    root.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, Any]] = []
    image_parts: list[dict[str, Any]] = []
    path_lines: list[str] = []

    for i, att in enumerate(attachments[:MAX_ATTACHMENTS]):
        name = _safe_name(getattr(att, "name", None) or getattr(att, "filename", None) or f"file{i}")
        mime = str(getattr(att, "mime_type", None) or "application/octet-stream").strip() or "application/octet-stream"
        b64 = getattr(att, "data_base64", None)
        if not isinstance(b64, str) or not b64.strip():
            raise ValueError(f"attachment {name!r}: missing data_base64")
        try:
            raw = base64.b64decode(b64.strip(), validate=True)
        except binascii.Error as exc:
            raise ValueError(f"attachment {name!r}: invalid base64") from exc
        if len(raw) > MAX_BYTES_PER_FILE:
            raise ValueError(f"attachment {name!r}: exceeds {MAX_BYTES_PER_FILE} bytes")

        dest = root / name
        dest.write_bytes(raw)
        rel = dest.relative_to(working_dir.resolve())
        path_lines.append(str(rel).replace("\\", "/"))
        summaries.append({"name": name, "mime_type": mime, "byte_length": len(raw), "path": str(rel).replace("\\", "/")})

        if mime.startswith("image/") and model_id_supports_vision(model_id):
            uri = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
            image_parts.append({"type": "image_url", "image_url": {"url": uri}})

    extra = "\n\n[Attached files are available in the workspace at:]\n" + "\n".join(f"- {p}" for p in path_lines)

    if image_parts and model_id_supports_vision(model_id):
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt + extra}]
        content.extend(image_parts)
        return content, summaries

    return prompt + extra, summaries
