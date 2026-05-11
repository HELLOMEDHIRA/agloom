"""Ensure project-local ``agloom.yaml`` and ``.agloom/sessions/*.json`` session records.

Stdio and WebSocket runtimes call this so a fresh checkout gets a starter config and each AGP
session leaves a small JSON marker under ``.agloom/sessions/``. If the process cwd is inside
``…/project/.agloom`` (common when a launcher cds into the state dir), paths anchor at *project*
so ``agloom.yaml`` and ``.agloom/sessions/`` match a normal tree next to the project root."""

from __future__ import annotations

import json
import re
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


def ensure_agloom_workspace(cwd: Path | None = None) -> tuple[Path, bool]:
    """Create ``agloom.yaml`` when missing; ensure ``.agloom/sessions/`` exists.

    Returns:
        ``(sessions_dir_path, created_yaml)`` — ``created_yaml`` is True only when a new file was written.
    """
    start = (cwd or Path.cwd()).resolve()
    project_root, agloom_root = _project_and_dot_agloom(start)
    sessions_dir = agloom_root / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    yaml_path = project_root / "agloom.yaml"
    created = False
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
