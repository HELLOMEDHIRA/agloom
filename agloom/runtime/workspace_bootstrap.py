"""Workspace path resolution and optional session JSON markers.

The **npm** ``agloom`` client calls ``ensureAgloomCliWorkspace`` before spawning the runtime; when
you start **only** ``agloom-runtime serve``, :func:`ensure_agloom_workspace` is invoked from the
serve entry so the same starter ``.agloom/agloom.yaml`` (and optional legacy root ``agloom.yaml``) and
``.agloom/{rules,skills,sessions}`` appear when missing. Session markers use :func:`write_session_started_json`. ``DEFAULT_AGLOOM_YAML`` matches
the CLI default template (``agloom_cli`` ``defaultAgloomTemplate`` / ``config``) for parity.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from collections.abc import Sequence
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_RULES_README = """Add rule files here (*.md, *.mdc). Set rules.dir in agloom.yaml to use another folder.
"""

_AGSUPERBRAIN_MCP_YAML = """name: agsuperbrain
transport: stdio
command: agsuperbrain
args:
  - mcp-serve
timeout: 120.0
"""

def _has_agsuperbrain_server(servers: object) -> bool:
    if not isinstance(servers, list):
        return False
    for s in servers:
        if isinstance(s, str):
            if s.split(":", 1)[0].strip().lower() == "agsuperbrain":
                return True
        if isinstance(s, dict) and str(s.get("name", "")).strip().lower() == "agsuperbrain":
            return True
    return False


def _ensure_agsuperbrain_mcp_in_nested_yaml(path: Path) -> None:
    """If project YAML has no agsuperbrain MCP entry, add the stdio shim path (matches npm bootstrap)."""
    if not path.is_file():
        return
    try:
        raw = path.read_text(encoding="utf-8")
        doc = yaml.safe_load(raw)
        if not isinstance(doc, dict):
            return
        mcp = doc.get("mcp")
        mcp_dict: dict[str, object] = dict(mcp) if isinstance(mcp, dict) else {}
        servers = list(mcp_dict.get("servers") or []) if isinstance(mcp_dict.get("servers"), list) else []
        if _has_agsuperbrain_server(servers):
            return
        servers.append("agsuperbrain:mcp/agsuperbrain.yaml")
        mcp_dict["servers"] = servers
        doc["mcp"] = mcp_dict
        path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print(
            "[agloom-runtime] added default mcp.servers entry agsuperbrain:mcp/agsuperbrain.yaml",
            file=sys.stderr,
            flush=True,
        )
    except (OSError, yaml.YAMLError, TypeError, ValueError) as exc:
        print(
            f"[agloom-runtime] could not patch MCP in {path}: {exc}",
            file=sys.stderr,
            flush=True,
        )


DEFAULT_AGLOOM_YAML = """# Agloom — https://github.com/HELLOMEDHIRA/agloom
# CLI merges layers (see agloom_cli/docs/config.md): ~/.agloom → walk-up → --config → flags.
#
# Defaults you usually edit (restart reloads YAML):
#   • model / ai.model — provider:id
#   • ai.system_prompt or top-level system_prompt
#   • mcp.servers — agsuperbrain → .agloom/mcp/agsuperbrain.yaml (stdio MCP; `agsuperbrain` CLI on PATH for mcp-serve)
#   • .agloom/rules/ — drop *.md / *.mdc files
#
# Merge is shallow per layer: a whole top-level `ai:` block replaces prior `ai` from earlier files.

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
  servers:
    - agsuperbrain:mcp/agsuperbrain.yaml

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
    """Scaffold ``.agloom/`` dirs and starter YAML when missing (also run from ``agloom-runtime serve`` stdio).

    When *args* is the runtime ``serve`` namespace, paths like ``--agent-store-path`` are used to
    locate ``<project>/.agloom`` even if the process ``cwd`` is not the project root (so starter
    files land next to the same tree that holds ``graph_store.sqlite``).

    Returns:
        ``(sessions_dir_path, created_yaml)`` — *created_yaml* is True if
        ``.agloom/agloom.yaml`` was written this call (new starter, or migrated from root-only).
    """
    start = (cwd or Path.cwd()).resolve()
    project_root, agloom_root = resolve_workspace_roots(start, args)
    agloom_root.mkdir(parents=True, exist_ok=True)
    for sub in ("rules", "skills", "sessions"):
        (agloom_root / sub).mkdir(parents=True, exist_ok=True)
    sessions_dir = agloom_root / "sessions"

    mcp_dir = agloom_root / "mcp"
    mcp_dir.mkdir(parents=True, exist_ok=True)
    ags_cfg = mcp_dir / "agsuperbrain.yaml"
    if not ags_cfg.is_file():
        ags_cfg.write_text(_AGSUPERBRAIN_MCP_YAML, encoding="utf-8")
    rules_readme = agloom_root / "rules" / "README.txt"
    if not rules_readme.is_file():
        rules_readme.write_text(_DEFAULT_RULES_README, encoding="utf-8")

    created = False
    root_yaml = project_root / "agloom.yaml"
    nested_yaml = agloom_root / "agloom.yaml"
    if not nested_yaml.is_file():
        if root_yaml.is_file():
            nested_yaml.write_text(root_yaml.read_text(encoding="utf-8"), encoding="utf-8")
            created = True
            print(
                "[agloom-runtime] migrated root agloom.yaml → .agloom/agloom.yaml (canonical); "
                "remove the root copy if unused — nested wins when both exist",
                file=sys.stderr,
                flush=True,
            )
        else:
            nested_yaml.write_text(DEFAULT_AGLOOM_YAML, encoding="utf-8")
            created = True

    if nested_yaml.is_file():
        _ensure_agsuperbrain_mcp_in_nested_yaml(nested_yaml)

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

    def _ep(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    _ep(
        "[agloom-runtime] Super-Brain not initialized — running `agsuperbrain init` "
        "(first run may take 1–2 minutes). Progress from agsuperbrain follows below."
    )
    stop_hb = threading.Event()

    def _heartbeat() -> None:
        while not stop_hb.wait(4.0):
            _ep("[agloom-runtime] … still running `agsuperbrain init` (normal on first run)")

    hb = threading.Thread(target=_heartbeat, daemon=True)
    hb.start()
    r = None
    try:
        try:
            r = subprocess.run(
                ["agsuperbrain", "init"],
                cwd=str(project_root),
                check=False,
            )
        except FileNotFoundError:
            return
    finally:
        stop_hb.set()
        hb.join(timeout=0.3)

    if r is None:
        return
    if r.returncode == 0:
        _ep("[agloom-runtime] Super-Brain workspace ready (./.agsuperbrain)")
    else:
        _ep(f"[agloom-runtime] agsuperbrain init exited with code {r.returncode}")


def _safe_session_filename(session_id: str) -> str:
    """Filesystem-safe stem from session id (handles odd ``--session`` values)."""
    cleaned = re.sub(r"[^\w.\-+=]", "_", session_id.strip())
    return cleaned if cleaned else "session"


def session_marker_json_path(sessions_dir: Path, session_id: str) -> Path:
    """Path to ``<session_id>.json`` under *sessions_dir*."""
    return sessions_dir / f"{_safe_session_filename(session_id)}.json"


def json_safe_turns_for_marker(turns: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """JSON-round-trip turns so session marker files stay plain JSON (no surprise types)."""
    try:
        raw = json.dumps(list(turns), default=str)
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except (TypeError, ValueError):
        pass
    out: list[dict[str, Any]] = []
    for t in turns:
        if isinstance(t, dict):
            out.append({k: v for k, v in t.items()})
    return out


def merge_session_marker_thread_turns(
    sessions_dir: Path,
    session_id: str,
    *,
    thread_id: str,
    turns: Sequence[dict[str, Any]],
) -> Path | None:
    """Merge ``SessionMemory``-style turns into ``.agloom/sessions/<id>.json`` under ``conversation``.

    One AGP session may run multiple LangGraph threads (invoke / workers). Turns are stored per
    ``thread_id`` under ``conversation.by_thread`` so summarization and ``apop_last_turn`` stay
    reflected on disk for an auditable trace.
    """
    if not sessions_dir.is_dir():
        return None
    path = session_marker_json_path(sessions_dir, session_id)
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(prev, dict):
                existing = dict(prev)
        except (OSError, json.JSONDecodeError):
            existing = {}

    safe = json_safe_turns_for_marker(turns)
    conv = existing.get("conversation")
    if not isinstance(conv, dict):
        conv = {}
    by_raw = conv.get("by_thread")
    by_thread: dict[str, Any] = dict(by_raw) if isinstance(by_raw, dict) else {}
    by_thread[thread_id] = {
        "turns": safe,
        "updated_at": datetime.now(UTC).isoformat(),
        "turn_count": len(safe),
    }
    conv = {**conv, "by_thread": by_thread}
    existing["conversation"] = conv
    existing["session_id"] = session_id

    path.write_text(json.dumps(existing, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path


def attach_session_memory_to_session_marker(
    memory: Any,
    sessions_dir: Path,
    session_id: str,
) -> None:
    """If *memory* is :class:`~agloom.memory.session.SessionMemory`, persist turns to the session JSON."""
    from agloom.memory.session import SessionMemory

    if not sessions_dir.is_dir():
        return
    if not isinstance(memory, SessionMemory):
        return

    async def _persist(tid: str, tlist: list[dict[str, Any]]) -> None:
        merge_session_marker_thread_turns(sessions_dir, session_id, thread_id=tid, turns=tlist)

    memory.on_turns_async = _persist


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

    Top-level ``conversation`` (written by :func:`merge_session_marker_thread_turns`) is kept
    across marker rewrites when absent from *extra*.

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

    for pk in ("conversation",):
        if pk in existing and pk not in payload:
            payload[pk] = existing[pk]

    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path
