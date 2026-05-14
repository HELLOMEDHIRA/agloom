"""Stage ``command.invoke`` attachments on disk for stdio/WebSocket AGP (not imported by ``import agloom``)."""

from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..multimodal import guess_model_id, model_id_supports_vision

if TYPE_CHECKING:
    from ..protocol.commands import CommandInvoke

MAX_ATTACHMENTS = 8
MAX_BYTES_PER_FILE = 5 * 1024 * 1024


def _safe_name(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", (name or "file").strip())
    return s[:120] or "file"


def prepare_invoke_command(
    cmd: CommandInvoke,
    *,
    agent: Any,
    thread: str,
    working_dir: Path,
) -> tuple[Any, list[dict[str, Any]]]:
    """Return ``(prompt_or_content_list, attachment_summaries_for_wire)``."""
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
    """Write files under ``.agloom/attachments/<thread>/``; return user turn + wire summary dicts."""
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


__all__ = [
    "MAX_ATTACHMENTS",
    "MAX_BYTES_PER_FILE",
    "prepare_invoke_attachments",
    "prepare_invoke_command",
]
