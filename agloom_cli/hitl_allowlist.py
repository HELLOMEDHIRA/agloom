"""Persisted HITL allowlists (tools, patterns, workers) under ``storage_dir()``."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

ALLOWLIST_VERSION = 1

_DEFAULT_BASENAME = "tool_allowlist.json"


def resolve_allowlist_path(storage_root: Path, basename: str | None = None) -> Path:
    """Resolve ``<.agloom>/<basename>`` for HITL allowlist storage.

    The file always lives **inside** the active CLI storage root (per-project ``.agloom`` when
    ``set_cli_project_root`` is set). *basename* must be a single filename — no directories,
    ``..``, or absolute paths — so the allowlist cannot escape the project store.

    Args:
        storage_root: Resolved storage directory (e.g. :func:`agloom_cli.config.storage_dir`).
        basename: Optional filename; empty or omitted → ``tool_allowlist.json``.

    Raises:
        ValueError: If *basename* is unsafe or resolves outside *storage_root*.
    """
    root = storage_root.resolve()
    raw = (basename or _DEFAULT_BASENAME).strip()
    name = raw if raw else _DEFAULT_BASENAME
    if name in (".", ".."):
        raise ValueError("allowlist_file must be a normal filename.")
    if Path(name).name != name:
        raise ValueError(
            "allowlist_file must be a basename only (no path segments); "
            "it always lives under the project .agloom directory."
        )
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"Allowlist path must be under {root}")
    return candidate


def default_allowlist_path(storage_root: Path) -> Path:
    """Backward-compatible alias for ``resolve_allowlist_path(storage_root, None)``."""
    return resolve_allowlist_path(storage_root, None)


def load_allowlist(path: Path) -> dict[str, list[str]]:
    """Return normalized allowlist dict with keys tools, patterns, workers."""
    if not path.exists():
        return {"tools": [], "patterns": [], "workers": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"tools": [], "patterns": [], "workers": []}
    if not isinstance(raw, dict):
        return {"tools": [], "patterns": [], "workers": []}
    out: dict[str, list[str]] = {"tools": [], "patterns": [], "workers": []}
    for key in ("tools", "patterns", "workers"):
        val = raw.get(key, [])
        if isinstance(val, list):
            out[key] = sorted({str(x).strip() for x in val if str(x).strip()})
        elif isinstance(val, str) and val.strip():
            out[key] = [val.strip()]
    return out


def save_allowlist(path: Path, data: dict[str, list[str]]) -> None:
    """Atomically write allowlist JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def _norm(key: str) -> list[str]:
        raw_list = data.get(key, [])
        out: set[str] = set()
        if not isinstance(raw_list, list):
            return []
        for x in raw_list:
            s = x.strip() if isinstance(x, str) else str(x).strip()
            if s:
                out.add(s)
        return sorted(out)

    payload: dict[str, Any] = {
        "version": ALLOWLIST_VERSION,
        "tools": _norm("tools"),
        "patterns": _norm("patterns"),
        "workers": _norm("workers"),
    }
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def merge_allowlist_file(
    path: Path,
    *,
    tools: list[str] | None = None,
    patterns: list[str] | None = None,
    workers: list[str] | None = None,
) -> dict[str, list[str]]:
    """Load, merge new ids, save, and return the merged dict."""
    cur = load_allowlist(path)
    if tools:
        cur["tools"] = sorted(set(cur["tools"]) | {t.strip() for t in tools if t.strip()})
    if patterns:
        cur["patterns"] = sorted(set(cur["patterns"]) | {p.strip() for p in patterns if p.strip()})
    if workers:
        cur["workers"] = sorted(set(cur["workers"]) | {w.strip() for w in workers if w.strip()})
    save_allowlist(path, cur)
    return cur
