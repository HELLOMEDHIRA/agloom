"""Shared path containment and safe filename helpers for runtime I/O."""

from __future__ import annotations

import os
import re
from pathlib import Path


def safe_single_segment_filename(
    name: str,
    *,
    fallback: str = "file",
    max_len: int = 120,
) -> str:
    """Sanitize to one path segment (no directory separators); strip leading dots."""
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", (name or "").strip() or fallback)
    s = s[:max_len] or fallback
    s = s.lstrip(".")
    if not s or s in (".", ".."):
        return fallback
    if "/" in s or "\\" in s or "\x00" in s:
        return fallback
    return s


def assert_resolved_path_under_root(path: Path, root: Path, *, what: str) -> Path:
    """Resolve *path* and ensure it stays under *root* (``commonpath`` + ``normcase``)."""
    root_resolved = root.resolve()
    resolved = path.resolve()
    try:
        common = os.path.commonpath((str(root_resolved), str(resolved)))
    except ValueError as exc:
        raise ValueError(f"{what} escapes working directory") from exc
    if os.path.normcase(common) != os.path.normcase(str(root_resolved)):
        raise ValueError(f"{what} escapes working directory")
    return resolved
