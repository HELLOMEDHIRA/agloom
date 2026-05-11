"""Ensure project-local ``agloom.yaml``, legacy ``.agloom/agloom.yaml``, and Rich-era dirs.

Stdio and WebSocket runtimes call this so a fresh checkout gets:

- ``<project>/agloom.yaml`` — primary config (Node CLI walk-up discovery).
- ``<project>/.agloom/agloom.yaml`` — same starter template when missing (pre-migration Rich CLI).
- ``<project>/.agloom/{rules,skills,sessions}/`` — empty dirs for project rules, mirrored skills, session JSON.

If the process cwd is inside ``…/project/.agloom``, paths anchor at *project* so layout matches
that project root."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Keep in sync with ``agloom_cli/src/commands/init.ts`` template (CLI ``agloom init``).
DEFAULT_AGLOOM_YAML = """# Agloom — https://github.com/HELLOMEDHIRA/agloom
# CLI merges this file (walk-up discovery; override with `agloom --config <path>`).
# Keys are top-level — see agloom_cli/docs/config.md
model: groq:meta-llama/llama-3.3-70b-versatile
# provider: groq
"""


def _project_and_dot_agloom(cwd: Path) -> tuple[Path, Path]:
    """Map *cwd* to ``(project_root, .agloom_dir)``.

    If *cwd* is ``…/project/.agloom`` or anywhere under that tree, *project_root* is ``…/project``
    and *.agloom_dir* is ``…/project/.agloom``. Otherwise *project_root* is *cwd* and *.agloom_dir*
    is ``cwd / ".agloom"`` (normal project layout).
    """
    start = cwd.resolve()
    cur: Path = start
    while True:
        if cur.name == ".agloom":
            return cur.parent, cur
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return start, start / ".agloom"


def path_hints_from_runtime_args(args: Any) -> tuple[str | None, ...]:
    """Paths that often sit under ``<project>/.agloom/`` — used to find *project* when ``cwd`` mismatches."""
    hints: list[str | None] = []
    hints.append(getattr(args, "agent_store_path", None) or ".agloom/graph_store.sqlite")
    if getattr(args, "store", None) == "sqlite":
        sp = getattr(args, "store_path", None)
        if sp:
            hints.append(sp)
    mp = getattr(args, "memory_path", None)
    if mp:
        hints.append(mp)
    elif str(getattr(args, "memory_type", "") or "").strip().lower() == "sqlite":
        hints.append(".agloom/session_memory.sqlite")
    return tuple(hints)


def _roots_from_dot_agloom_path_hints(cwd: Path, hints: Sequence[str | None]) -> tuple[Path, Path] | None:
    """If any hint resolves under a ``…/.agloom/…`` path, return ``(project_root, that .agloom dir)``."""
    start = cwd.resolve()
    for raw in hints:
        if not raw:
            continue
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (start / p).resolve()
        else:
            p = p.resolve()
        cur = p
        while True:
            if cur.name == ".agloom":
                return cur.parent, cur
            parent = cur.parent
            if parent == cur:
                break
            cur = parent
    return None


def resolve_workspace_roots(start: Path, args: Any | None) -> tuple[Path, Path]:
    """``(project_root, dot_agloom_dir)`` for layout files — prefers hints from *args* when cwd is wrong."""
    root = start.resolve()
    if args is not None:
        hit = _roots_from_dot_agloom_path_hints(root, path_hints_from_runtime_args(args))
        if hit is not None:
            return hit
    return _project_and_dot_agloom(root)


def ensure_agloom_workspace(cwd: Path | None = None, *, args: Any | None = None) -> tuple[Path, bool]:
    """Scaffold ``.agloom/`` dirs and starter YAML when missing.

    When *args* is the runtime ``serve`` namespace, paths like ``--agent-store-path`` are used to
    locate ``<project>/.agloom`` even if the process ``cwd`` is not the project root (so starter
    files land next to the same tree that holds ``graph_store.sqlite``).

    Returns:
        ``(sessions_dir_path, created_yaml)`` — ``created_yaml`` is True if any starter YAML was written.
    """
    start = (cwd or Path.cwd()).resolve()
    project_root, agloom_root = resolve_workspace_roots(start, args)
    agloom_root.mkdir(parents=True, exist_ok=True)
    for sub in ("rules", "skills", "sessions"):
        (agloom_root / sub).mkdir(parents=True, exist_ok=True)
    sessions_dir = agloom_root / "sessions"

    created = False
    for yaml_path in (project_root / "agloom.yaml", agloom_root / "agloom.yaml"):
        if not yaml_path.is_file():
            yaml_path.write_text(DEFAULT_AGLOOM_YAML, encoding="utf-8")
            created = True

    return sessions_dir, created


def _safe_session_filename(session_id: str) -> str:
    """Filesystem-safe stem from session id (handles odd ``--session`` values)."""
    cleaned = re.sub(r"[^\w.\-+=]", "_", session_id.strip())
    return cleaned if cleaned else "session"


def write_session_started_json(
    sessions_dir: Path,
    session_id: str,
    *,
    transport: str,
    thread: str | None = None,
    record_cwd: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write ``<session_id>.json`` when a serve loop / WS connection starts."""
    sessions_dir.mkdir(parents=True, exist_ok=True)
    root = (record_cwd or Path.cwd()).resolve()
    payload: dict[str, Any] = {
        "session_id": session_id,
        "started_at": datetime.now(UTC).isoformat(),
        "cwd": str(root),
        "transport": transport,
    }
    if thread:
        payload["initial_thread"] = thread
    if extra:
        payload.update(extra)

    path = sessions_dir / f"{_safe_session_filename(session_id)}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
