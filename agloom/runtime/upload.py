"""Stage user-attached files under the CLI tools working directory (AGP ``command.attach.file``)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from .path_safety import assert_resolved_path_under_root, safe_single_segment_filename

_DEFAULT_MAX_BYTES = 8 * 1024 * 1024
# Cumulative cap per resolved working root (process-wide, best-effort accounting).
_MAX_TOTAL_UPLOAD_BYTES_PER_ROOT = 256 * 1024 * 1024
_upload_totals_by_root: dict[str, int] = {}


def _root_quota_key(root: Path) -> str:
    resolved = str(root.resolve())
    if os.name == "nt":
        return os.path.normcase(resolved)
    return resolved


def release_upload_quota(agent: Any, nbytes: int) -> None:
    """Decrement cumulative upload accounting for the agent working root."""
    if nbytes <= 0:
        return
    root_key = _root_quota_key(_working_root(agent))
    prev = _upload_totals_by_root.get(root_key, 0)
    _upload_totals_by_root[root_key] = max(0, prev - nbytes)


def _working_root(agent: Any) -> Path:
    cli = getattr(agent, "config", {}).get("cli_tools") or {}
    raw = cli.get("working_dir") if isinstance(cli, dict) else None
    root = Path(str(raw or ".")).expanduser().resolve()
    return root


def _safe_basename(filename: str) -> str:
    return safe_single_segment_filename(
        Path(filename).name.strip() or "upload.bin",
        fallback="upload.bin",
        max_len=120,
    )


def stage_attached_bytes(agent: Any, *, filename: str, raw: bytes, max_bytes: int = _DEFAULT_MAX_BYTES) -> tuple[str, int]:
    """Write *raw* to ``<working_dir>/.agloom_uploads/<uuid>_<basename>``.

    Returns ``(relative_path_from_working_root, byte_length)``.
    """
    if len(raw) > max_bytes:
        raise ValueError(f"attachment exceeds limit ({max_bytes} bytes)")
    root = _working_root(agent)
    root_key = _root_quota_key(root)
    prev = _upload_totals_by_root.get(root_key, 0)
    if prev + len(raw) > _MAX_TOTAL_UPLOAD_BYTES_PER_ROOT:
        raise ValueError(
            f"upload quota exceeded for this working directory ({_MAX_TOTAL_UPLOAD_BYTES_PER_ROOT} bytes cumulative)"
        )

    upload_dir = root / ".agloom_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    assert_resolved_path_under_root(upload_dir, root, what="upload directory")

    base = _safe_basename(filename)
    dest = upload_dir / f"{uuid4().hex[:12]}_{base}"
    dest_resolved = assert_resolved_path_under_root(dest, root, what="attachment path")
    try:
        dest_resolved.write_bytes(raw)
    except OSError:
        raise
    _upload_totals_by_root[root_key] = prev + len(raw)
    rel = dest_resolved.relative_to(root.resolve())
    return str(rel).replace("\\", "/"), len(raw)
