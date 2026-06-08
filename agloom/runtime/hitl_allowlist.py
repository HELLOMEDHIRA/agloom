"""Persist HITL tool allowlist decisions (``decision=allowlist``) for stable runtime restarts."""

from __future__ import annotations

import json
import logging
import os
from argparse import Namespace
from collections.abc import MutableSet
from pathlib import Path
from typing import Any

from ..cli_tools.safety_metadata import tools_path_scoped_allowlist
from ..patterns.hitl_tool_coalesce import _canonical_read_path, build_default_hitl_coalescer
from .atomic_io import atomic_write_text

_log = logging.getLogger(__name__)

# Tools where Allowlist (A) grants a path prefix, not a session-wide tool name.
_PATH_SCOPED_ALLOWLIST_TOOLS = tools_path_scoped_allowlist()


class HitlAllowlistPolicy:
    """Session HITL allowlist: global tool names plus optional per-path grants."""

    __slots__ = ("_tools", "_path_prefixes")

    def __init__(
        self,
        tools: set[str] | None = None,
        path_prefixes: dict[str, list[str]] | None = None,
    ) -> None:
        self._tools: set[str] = set(tools or ())
        self._path_prefixes: dict[str, list[str]] = {
            k: list(v) for k, v in (path_prefixes or {}).items()
        }

    def global_tools(self) -> set[str]:
        return set(self._tools)

    def path_prefixes_dict(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self._path_prefixes.items()}

    def allows(self, tool_name: str, tool_args: dict[str, Any]) -> bool:
        if tool_name in self._tools:
            return True
        prefixes = self._path_prefixes.get(tool_name)
        if not prefixes:
            return False
        canon = _path_from_tool_args(tool_name, tool_args)
        if not canon:
            return False
        return any(_path_matches_prefix(canon, p) for p in prefixes)

    def apply_allowlist_decision(self, tool_name: str, tool_args: dict[str, Any]) -> None:
        """Record an Allowlist (A) grant from the UI — path-scoped for read tools."""
        if tool_name in _PATH_SCOPED_ALLOWLIST_TOOLS:
            canon = _path_from_tool_args(tool_name, tool_args)
            if canon:
                self._add_path_prefix(tool_name, canon)
                return
        self._tools.add(tool_name)

    def add_global_tool(self, tool_name: str) -> None:
        self._tools.add(tool_name)

    def _add_path_prefix(self, tool_name: str, canonical_path: str) -> None:
        lst = self._path_prefixes.setdefault(tool_name, [])
        if canonical_path not in lst:
            lst.append(canonical_path)

    # Legacy ``set`` compatibility for callers that still use ``tool in allowlist``.
    def __contains__(self, tool_name: object) -> bool:
        return isinstance(tool_name, str) and tool_name in self._tools

    def add(self, tool_name: str) -> None:
        self._tools.add(tool_name)


def _path_from_tool_args(tool_name: str, tool_args: dict[str, Any]) -> str | None:
    if tool_name not in _PATH_SCOPED_ALLOWLIST_TOOLS:
        return None
    raw = tool_args.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return _canonical_read_path(raw)


def _path_matches_prefix(canon: str, prefix: str) -> bool:
    if canon == prefix:
        return True
    sep = os.sep
    return canon.startswith(prefix + sep) or canon.startswith(prefix + "/")


def is_hitl_allowlisted(
    allowlist: MutableSet[str] | HitlAllowlistPolicy | None,
    tool_name: str,
    tool_args: dict[str, Any],
) -> bool:
    if allowlist is None:
        return False
    if isinstance(allowlist, HitlAllowlistPolicy):
        return allowlist.allows(tool_name, tool_args)
    return tool_name in allowlist


def apply_hitl_allowlist_decision(
    allowlist: MutableSet[str] | HitlAllowlistPolicy | None,
    tool_name: str,
    tool_args: dict[str, Any],
) -> None:
    if allowlist is None or not tool_name:
        return
    if isinstance(allowlist, HitlAllowlistPolicy):
        allowlist.apply_allowlist_decision(tool_name, tool_args)
    else:
        allowlist.add(tool_name)


def _read_session_marker_dict(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        data: Any = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        if not isinstance(exc, FileNotFoundError):
            _log.warning("session marker JSON invalid or unreadable %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def load_allowlist_from_session_marker(path: Path) -> set[str]:
    """Load ``hitl_tool_allowlist`` array from a session marker ``.json``."""
    return load_policy_from_session_marker(path).global_tools()


def load_policy_from_session_marker(path: Path) -> HitlAllowlistPolicy:
    """Load global tool allowlist and ``hitl_path_allowlist`` path prefixes from a session marker."""
    data = _read_session_marker_dict(path)
    tools_raw = data.get("hitl_tool_allowlist")
    tools: set[str] = set()
    if isinstance(tools_raw, list):
        tools = {str(x).strip() for x in tools_raw if str(x).strip()}
    path_rules: dict[str, list[str]] = {}
    raw_paths = data.get("hitl_path_allowlist")
    if isinstance(raw_paths, dict):
        for tool, prefixes in raw_paths.items():
            if not isinstance(tool, str) or not isinstance(prefixes, list):
                continue
            cleaned = [str(p).strip() for p in prefixes if str(p).strip()]
            if cleaned:
                path_rules[tool.strip()] = cleaned
    return HitlAllowlistPolicy(tools=tools, path_prefixes=path_rules)


def save_allowlist_to_session_marker(path: Path, tools: set[str]) -> None:
    """Merge sorted ``hitl_tool_allowlist`` into an existing session marker JSON (preserve keys)."""
    save_policy_to_session_marker(path, HitlAllowlistPolicy(tools=tools))


def save_policy_to_session_marker(path: Path, policy: HitlAllowlistPolicy) -> None:
    """Merge allowlist policy fields into an existing session marker JSON (preserve keys)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    marker: dict[str, Any] = dict(_read_session_marker_dict(path) if path.is_file() else {})
    marker["hitl_tool_allowlist"] = sorted(policy.global_tools())
    paths = policy.path_prefixes_dict()
    if paths:
        marker["hitl_path_allowlist"] = {k: sorted(v) for k, v in sorted(paths.items())}
    elif "hitl_path_allowlist" in marker:
        marker["hitl_path_allowlist"] = {}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_coalesce_grants_from_session_marker(path: Path) -> list[dict[str, Any]]:
    """Load ``hitl_coalesce_grants`` from a session marker (recent-approval dedupe across restarts)."""
    data = _read_session_marker_dict(path)
    raw = data.get("hitl_coalesce_grants")
    if not isinstance(raw, list):
        return []
    return [g for g in raw if isinstance(g, dict)]


def save_coalesce_grants_to_session_marker(path: Path, grants: list[dict[str, Any]]) -> None:
    """Merge ``hitl_coalesce_grants`` into the session marker JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_session_marker_dict(path) if path.is_file() else {}
    existing["hitl_coalesce_grants"] = grants
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def hitl_allowlist_paths_for_runtime(
    args: Namespace,
    *,
    session_marker_json: Path | None,
    session_scoped: bool,
    cwd: Path | None = None,
) -> tuple[HitlAllowlistPolicy, Path | None, Path | None]:
    """Resolve initial allowlist policy and persistence targets.

    Returns ``(policy, legacy_hitl_json_path, session_marker_json_path)``.

    **Session-scoped** (stdio): persist into ``session_marker_json`` only; seed from that file if
    present, otherwise from ``.agloom/hitl_tool_allowlist.json``.

    **Non-session** (e.g. WebSocket shared agent): legacy global JSON under ``.agloom/`` only.

    Explicit ``--hitl-allowlist-path`` always uses that legacy file.
    """
    cwd = cwd or Path.cwd()
    global_fallback = cwd / ".agloom" / "hitl_tool_allowlist.json"

    if getattr(args, "no_hitl_allowlist_persist", False):
        return HitlAllowlistPolicy(), None, None

    raw_explicit = getattr(args, "hitl_allowlist_path", None)
    if isinstance(raw_explicit, str) and raw_explicit.strip():
        p = Path(raw_explicit).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return HitlAllowlistPolicy(tools=load_tool_allowlist(p)), p, None

    if not session_scoped or session_marker_json is None:
        global_fallback.parent.mkdir(parents=True, exist_ok=True)
        return HitlAllowlistPolicy(tools=load_tool_allowlist(global_fallback)), global_fallback, None

    session_marker_json.parent.mkdir(parents=True, exist_ok=True)
    if session_marker_json.is_file():
        policy = load_policy_from_session_marker(session_marker_json)
        if not policy.global_tools() and not policy.path_prefixes_dict():
            policy = HitlAllowlistPolicy(tools=load_tool_allowlist(global_fallback))
    else:
        policy = HitlAllowlistPolicy(tools=load_tool_allowlist(global_fallback))
    return policy, None, session_marker_json


def build_session_hitl_coalescer(
    session_marker_json: Path | None = None,
    **_: Any,
) -> Any:
    """Fresh per-session coalescer (cleared again at each user prompt in the runtime bridge)."""
    del session_marker_json
    return build_default_hitl_coalescer()


def load_tool_allowlist(path: Path) -> set[str]:
    """Load tool names from JSON ``{"tools": ["execute", ...]}``; missing file → empty."""
    try:
        raw = path.read_text(encoding="utf-8")
        data: Any = json.loads(raw)
    except FileNotFoundError:
        return set()
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("HITL allowlist file invalid JSON %s: %s", path, exc)
        return set()
    tools = data.get("tools") if isinstance(data, dict) else None
    if not isinstance(tools, list):
        return set()
    return {str(x).strip() for x in tools if str(x).strip()}


def save_tool_allowlist(path: Path, tools: set[str]) -> None:
    """Atomically write sorted unique tool names."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tools": sorted(tools)}
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
