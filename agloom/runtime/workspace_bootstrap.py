"""Workspace path resolution and optional session JSON markers.

The **npm** ``agloom`` client calls ``ensureAgloomCliWorkspace`` before spawning the runtime; when
you start **only** ``agloom-runtime serve``, :func:`ensure_agloom_workspace` is invoked from the
serve entry so the same starter ``agloom.yaml`` and ``.agloom/{rules,skills,sessions}`` appear when
missing. Session markers use :func:`write_session_started_json`. ``DEFAULT_AGLOOM_YAML`` matches
the CLI default template (``agloom_cli`` ``defaultAgloomTemplate`` / ``config``) for parity.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_AGLOOM_YAML = """# Agloom — https://github.com/HELLOMEDHIRA/agloom
# CLI merges this file (walk-up discovery; override with `agloom --config <path>`).
# Nested blocks (`ai`, `memory`, …) are flattened by the CLI config loader.

ai:
  name: agloom
  model: auto
  system_prompt: |
    You are an autonomous AI programming assistant built with agloom.

    ## Your Capabilities

    You have access to tools for:

    - File operations: read, write, list, search, create, remove files and directories
    - Shell commands: execute commands in the terminal
    - Web search: search the web for documentation, bugs, or solutions
    - HTTP requests: make API calls when needed
    - Task planning: break down complex tasks into steps
    - Working directory: navigate and manage project context

    ## Guidelines

    1. Always prefer existing code - Don't suggest rewriting unless necessary
    2. Be concise - Give focused answers, not lengthy explanations
    3. Think step-by-step - For complex tasks, plan before executing
    4. Use tools wisely - Check file context before modifying
    5. Handle errors - gracefully explain what went wrong
    6. Respect user privacy - Don't log or store sensitive data

    ## Code Style

    - Follow existing conventions in the codebase
    - Use meaningful variable names
    - Add comments for complex logic
    - Keep functions small and focused

    ## Error Handling

    When you make mistakes or hit dead ends:

    - Acknowledge the error clearly
    - Explain what happened and why
    - Show what you tried and the outcome
    - Offer the next best approach

    ## Communication

    - Use markdown for code blocks
    - Show actual vs expected behavior for bugs
    - Suggest specific fixes
    - Ask clarification when requirements are unclear

    Remember: You're collaborating with a human. They control the session, you assist.

mcp:
  servers: []

tools:
  dir: ''
  disabled: []
  cli_enabled: true

memory:
  enabled: true
  max_turns: 50
  auto_summarize: true

skills:
  enabled: true
  max_skills: 30

rules:
  dir: ''
  refresh: false

execution:
  max_concurrent: 4
  max_retries: 2
  llm_timeout: 120.0
  classifier_timeout: 30.0

safety:
  require_approval: true
  auto_approve: ''
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


def sessions_dir_for_runtime(cwd: Path | None = None, *, args: Any | None = None) -> Path:
    """Resolve ``<project>/.agloom/sessions`` for session markers — does not create directories."""
    start = (cwd or Path.cwd()).resolve()
    _project_root, agloom_root = resolve_workspace_roots(start, args)
    return agloom_root / "sessions"


def ensure_agloom_workspace(cwd: Path | None = None, *, args: Any | None = None) -> tuple[Path, bool]:
    """Scaffold ``.agloom/`` dirs and starter YAML when missing (tests / tooling; not used by serve).

    When *args* is the runtime ``serve`` namespace, paths like ``--agent-store-path`` are used to
    locate ``<project>/.agloom`` even if the process ``cwd`` is not the project root (so starter
    files land next to the same tree that holds ``graph_store.sqlite``).

    Returns:
        ``(sessions_dir_path, created_yaml)`` — ``created_yaml`` is True if starter
        ``agloom.yaml`` was written at *project_root* (only when neither root nor
        legacy ``.agloom/agloom.yaml`` exists).
    """
    start = (cwd or Path.cwd()).resolve()
    project_root, agloom_root = resolve_workspace_roots(start, args)
    agloom_root.mkdir(parents=True, exist_ok=True)
    for sub in ("rules", "skills", "sessions"):
        (agloom_root / sub).mkdir(parents=True, exist_ok=True)
    sessions_dir = agloom_root / "sessions"

    created = False
    root_yaml = project_root / "agloom.yaml"
    nested_yaml = agloom_root / "agloom.yaml"
    if not root_yaml.is_file() and not nested_yaml.is_file():
        root_yaml.write_text(DEFAULT_AGLOOM_YAML, encoding="utf-8")
        created = True

    return sessions_dir, created


def bootstrap_optional_agsuperbrain(cwd: Path | None = None, *, args: Any | None = None) -> None:
    """Run ``agsuperbrain init`` once when ``.agsuperbrain`` is missing (mirrors npm CLI bootstrap).

    Failure is non-fatal: binary may be absent or init may return non-zero.
    """
    start = (cwd or Path.cwd()).resolve()
    project_root, _ = resolve_workspace_roots(start, args)
    agsuperbrain_dir = project_root / ".agsuperbrain"
    if agsuperbrain_dir.exists():
        return
    try:
        r = subprocess.run(
            ["agsuperbrain", "init"],
            cwd=str(project_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return
    if r.returncode != 0 and r.stderr:
        import sys

        tail = r.stderr.strip()
        if tail:
            sys.stderr.write(f"[agloom-runtime] agsuperbrain init: {tail}\n")


def _safe_session_filename(session_id: str) -> str:
    """Filesystem-safe stem from session id (handles odd ``--session`` values)."""
    cleaned = re.sub(r"[^\w.\-+=]", "_", session_id.strip())
    return cleaned if cleaned else "session"


def session_marker_json_path(sessions_dir: Path, session_id: str) -> Path:
    """Path to ``<session_id>.json`` under *sessions_dir*."""
    return sessions_dir / f"{_safe_session_filename(session_id)}.json"


def write_session_started_json(
    sessions_dir: Path,
    session_id: str,
    *,
    transport: str,
    thread: str | None = None,
    record_cwd: Path | None = None,
    extra: dict[str, Any] | None = None,
    hitl_tool_allowlist: Sequence[str] | None = None,
) -> Path | None:
    """Write ``<session_id>.json`` if *sessions_dir* exists (CLI creates ``.agloom/``).

    *extra* may include ``effective_config`` (non-secret snapshot of runtime argv/YAML merge at
    process start). Editing this file does not hot-reload the running bridge; restart the CLI
    or change settings via AGP (e.g. ``command.config.set``) to apply new models or limits.

    If the marker file already exists for *session_id*, ``started_at`` and ``hitl_tool_allowlist``
    are preserved unless new values are supplied (resume-safe).
    """
    if not sessions_dir.is_dir():
        return None
    root = (record_cwd or Path.cwd()).resolve()
    path = session_marker_json_path(sessions_dir, session_id)

    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(prev, dict):
                existing = prev
        except (OSError, json.JSONDecodeError):
            existing = {}

    started_at = datetime.now(UTC).isoformat()
    if existing.get("session_id") == session_id and existing.get("started_at"):
        started_at = str(existing["started_at"])

    payload: dict[str, Any] = {
        "session_id": session_id,
        "started_at": started_at,
        "cwd": str(root),
        "transport": transport,
    }
    if thread:
        payload["initial_thread"] = thread

    if hitl_tool_allowlist is not None:
        payload["hitl_tool_allowlist"] = list(hitl_tool_allowlist)
    elif isinstance(existing.get("hitl_tool_allowlist"), list):
        payload["hitl_tool_allowlist"] = list(existing["hitl_tool_allowlist"])

    if extra:
        payload.update(extra)

    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path
