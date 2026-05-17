"""Stage ``command.invoke`` attachments on disk for stdio/WebSocket AGP (not imported by ``import agloom``)."""

from __future__ import annotations

import base64
import binascii
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..multimodal import guess_model_id, model_id_supports_vision
from .path_safety import assert_resolved_path_under_root, safe_single_segment_filename

if TYPE_CHECKING:
    from ..protocol.commands import CommandInvoke

MAX_ATTACHMENTS = 8
MAX_BYTES_PER_FILE = 5 * 1024 * 1024
MAX_TOTAL_ATTACHMENTS_BYTES = 40 * 1024 * 1024
MAX_BYTES_PER_THREAD = 20 * 1024 * 1024

_BLOCKED_EXECUTABLE_SUFFIXES = frozenset(
    {
        ".exe",
        ".dll",
        ".bat",
        ".cmd",
        ".com",
        ".msi",
        ".scr",
        ".ps1",
        ".vbs",
        ".js",
        ".jar",
        ".sh",
        ".bash",
        ".zsh",
        ".app",
        ".dmg",
        ".pkg",
        ".deb",
        ".rpm",
    }
)

_THREAD_TOTALS: dict[str, int] = {}

_MAGIC_MIME: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
)


def _safe_name(name: str) -> str:
    return safe_single_segment_filename(name or "file", fallback="file", max_len=120)


def _thread_quota_key(working_dir: Path, thread: str) -> str:
    return f"{working_dir.resolve()}::{_safe_name(thread)}"


def _sniff_mime(raw: bytes, declared: str) -> str:
    for prefix, mime in _MAGIC_MIME:
        if raw.startswith(prefix):
            return mime
    guessed, _ = mimetypes.guess_type(f"file.{declared.split('/')[-1]}")
    if guessed:
        return guessed
    return declared


def _reject_executable(name: str) -> None:
    suffix = Path(name).suffix.lower()
    if suffix in _BLOCKED_EXECUTABLE_SUFFIXES:
        raise ValueError(f"attachment {name!r}: executable file type is not allowed")


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
    wd = working_dir.resolve()
    assert_resolved_path_under_root(root, wd, what="attachments root")
    root.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, Any]] = []
    image_parts: list[dict[str, Any]] = []
    path_lines: list[str] = []
    total_raw = 0
    thread_key = _thread_quota_key(wd, thread)
    thread_total = _THREAD_TOTALS.get(thread_key, 0)

    for i, att in enumerate(attachments[:MAX_ATTACHMENTS]):
        name = _safe_name(getattr(att, "name", None) or getattr(att, "filename", None) or f"file{i}")
        _reject_executable(name)
        declared = str(getattr(att, "mime_type", None) or "application/octet-stream").strip() or "application/octet-stream"
        b64 = getattr(att, "data_base64", None)
        if not isinstance(b64, str) or not b64.strip():
            raise ValueError(f"attachment {name!r}: missing data_base64")
        try:
            raw = base64.b64decode(b64.strip(), validate=True)
        except binascii.Error as exc:
            raise ValueError(f"attachment {name!r}: invalid base64") from exc
        if len(raw) > MAX_BYTES_PER_FILE:
            raise ValueError(f"attachment {name!r}: exceeds {MAX_BYTES_PER_FILE} bytes")
        total_raw += len(raw)
        if total_raw > MAX_TOTAL_ATTACHMENTS_BYTES:
            raise ValueError(
                f"attachments exceed combined limit ({MAX_TOTAL_ATTACHMENTS_BYTES} bytes per command.invoke)"
            )
        if thread_total + total_raw > MAX_BYTES_PER_THREAD:
            raise ValueError(
                f"attachments exceed per-thread limit ({MAX_BYTES_PER_THREAD} bytes for thread {thread!r})"
            )

        mime = _sniff_mime(raw, declared)

        dest = root / name
        dest_resolved = assert_resolved_path_under_root(dest, wd, what="attachment file")
        dest_resolved.write_bytes(raw)
        rel = dest_resolved.relative_to(wd)
        path_lines.append(str(rel).replace("\\", "/"))
        summaries.append({"name": name, "mime_type": mime, "byte_length": len(raw), "path": str(rel).replace("\\", "/")})

        if mime.startswith("image/") and model_id_supports_vision(model_id):
            uri = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
            image_parts.append({"type": "image_url", "image_url": {"url": uri}})

    _THREAD_TOTALS[thread_key] = thread_total + total_raw

    extra = "\n\n[Attached files are available in the workspace at:]\n" + "\n".join(f"- {p}" for p in path_lines)

    if image_parts and model_id_supports_vision(model_id):
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt + extra}]
        content.extend(image_parts)
        return content, summaries

    return prompt + extra, summaries


__all__ = [
    "MAX_ATTACHMENTS",
    "MAX_BYTES_PER_FILE",
    "MAX_BYTES_PER_THREAD",
    "MAX_TOTAL_ATTACHMENTS_BYTES",
    "prepare_invoke_attachments",
    "prepare_invoke_command",
]
