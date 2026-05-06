"""Discover and summarize CLI session JSON files for ``agloom sessions``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import normalize_cli_session_id


def _first_user_preview(messages: list[Any], max_len: int = 56) -> str:
    for m in messages:
        if not isinstance(m, dict):
            continue
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if content is None:
            continue
        text = content if isinstance(content, str) else str(content)
        text = " ".join(text.split())
        if len(text) > max_len:
            return text[: max_len - 1] + "…"
        return text or "—"
    return "—"


def load_session_row(path: Path) -> dict[str, Any] | None:
    """Parse one ``sessions/<id>.json`` file into display metadata. Returns None if unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    sid = data.get("id")
    if not isinstance(sid, str) or not sid:
        sid = path.stem
    try:
        sid = normalize_cli_session_id(sid)
    except ValueError:
        sid = path.stem

    last_active = str(data.get("last_active") or data.get("started_at") or "")
    started_at = str(data.get("started_at") or "")
    turns = data.get("turns")
    if isinstance(turns, int):
        turns_i = turns
    else:
        try:
            turns_i = int(turns) if turns is not None else len(data.get("messages") or [])
        except (TypeError, ValueError):
            turns_i = 0

    messages = data.get("messages") if isinstance(data.get("messages"), list) else []
    preview = _first_user_preview(messages)

    last_run = data.get("last_run") if isinstance(data.get("last_run"), dict) else {}
    project_root = str(last_run.get("project_root") or "").strip()
    resolved = last_run.get("resolved") if isinstance(last_run.get("resolved"), dict) else {}
    mb = data.get("model_binding") if isinstance(data.get("model_binding"), dict) else {}
    bound_model = str(mb.get("effective_model") or "").strip()
    sess_ai = data.get("ai") if isinstance(data.get("ai"), dict) else {}
    overlay_model = str(sess_ai.get("model") or "").strip() if sess_ai else ""
    model = str(resolved.get("model") or "").strip() or bound_model or overlay_model

    return {
        "id": sid,
        "path": path,
        "last_active": last_active,
        "started_at": started_at,
        "turns": turns_i,
        "preview": preview,
        "project_root": project_root,
        "model": model,
    }


def list_session_rows(sessions_dir: Path) -> list[dict[str, Any]]:
    """Return newest-first rows for every ``*.json`` under *sessions_dir*."""
    if not sessions_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        row = load_session_row(path)
        if row is not None:
            rows.append(row)
    rows.sort(
        key=lambda r: (r.get("last_active") or r.get("started_at") or ""),
        reverse=True,
    )
    return rows


def get_config_current_session_id(project_config_loaded: dict[str, Any] | None) -> str | None:
    """Return normalized ``session.current_session`` from config dict if set."""
    if not project_config_loaded:
        return None
    raw = (project_config_loaded.get("session") or {}).get("current_session")
    if raw is None or raw == "":
        return None
    try:
        return normalize_cli_session_id(str(raw))
    except ValueError:
        return None
