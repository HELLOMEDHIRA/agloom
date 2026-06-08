"""Path sandbox and shared knobs for built-in CLI-oriented tools."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BackgroundShellJob:
    """One ``bash_background`` process (book-kept on :class:`SafetyContext`)."""

    proc: Any  # subprocess.Popen
    command: str
    started_at: float


@dataclass
class SafetyContext:
    """Resolved working-directory root and capability flags for filesystem / shell / network."""

    root: Path
    allow_shell: bool = True
    allow_network: bool = True
    sandbox: bool = True
    #: Resolved filesystem paths successfully read via ``read_file`` this session (for overwrite policy).
    recently_read_paths: set[str] = field(default_factory=set)
    #: Jobs started via ``bash_background`` (job id → handle).
    background_shell_jobs: dict[str, BackgroundShellJob] = field(default_factory=dict)


def resolve_safe_path(rel_or_abs: str, ctx: SafetyContext) -> Path:
    """Resolve *rel_or_abs* under ``ctx.root`` when sandboxing; reject traversal attempts."""
    raw = (rel_or_abs or ".").strip() or "."
    # Strip redundant prefixes like "./"
    candidate = Path(raw)
    if not ctx.sandbox:
        p = candidate.expanduser()
        if not p.is_absolute():
            p = (ctx.root / p).resolve()
        else:
            p = p.resolve()
        return p

    if candidate.is_absolute():
        root = ctx.root.resolve()
        try:
            full = candidate.resolve()
        except OSError as exc:
            raise ValueError(f"invalid path: {exc}") from exc
        if root not in full.parents and full != root:
            raise ValueError("absolute paths outside the working directory are not allowed")
        return full

    # Join relative to root; block `..` segments that escape root after resolution.
    joined = (ctx.root / candidate).resolve()
    root_resolved = ctx.root.resolve()
    try:
        joined.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("path escapes the configured working directory") from exc
    return joined


def split_command(argv_string: str) -> list[str]:
    """Split a command line for ``subprocess`` without invoking a shell (POSIX-aware)."""
    import shlex

    return shlex.split(argv_string, posix=os.name != "nt")
