"""Atomic text writes safe on POSIX and Windows."""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write *text* via a sibling ``.tmp`` file and ``os.replace`` (Windows-safe)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


__all__ = ["atomic_write_text"]
