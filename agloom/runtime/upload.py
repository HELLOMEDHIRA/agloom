"""Stage user-attached files under the CLI tools working directory (AGP ``command.attach.file``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

_DEFAULT_MAX_BYTES = 8 * 1024 * 1024


def _working_root(agent: Any) -> Path:
    cli = getattr(agent, "config", {}).get("cli_tools") or {}
    raw = cli.get("working_dir") if isinstance(cli, dict) else None
    root = Path(str(raw or ".")).expanduser().resolve()
    return root


def stage_attached_bytes(agent: Any, *, filename: str, raw: bytes, max_bytes: int = _DEFAULT_MAX_BYTES) -> tuple[str, int]:
    """Write *raw* to ``<working_dir>/.agloom_uploads/<uuid>_<basename>``.

    Returns ``(relative_path_from_working_root, byte_length)``.
    """
    if len(raw) > max_bytes:
        raise ValueError(f"attachment exceeds limit ({max_bytes} bytes)")
    root = _working_root(agent)
    upload_dir = root / ".agloom_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    base = Path(filename).name.strip() or "upload.bin"
    if base in (".", ".."):
        base = "upload.bin"
    dest = upload_dir / f"{uuid4().hex[:12]}_{base}"
    dest.write_bytes(raw)
    rel = dest.relative_to(root)
    return str(rel).replace("\\", "/"), len(raw)
