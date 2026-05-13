"""Minimal environment for CLI subprocess tools (shell, which, etc.).

Avoids passing through API keys and other secrets from the parent process.
"""

from __future__ import annotations

import os
from typing import Mapping

# Uppercase names — matched case-insensitively against ``os.environ``.
_BASE_ENV_KEYS: frozenset[str] = frozenset(
    {
        "PATH",
        "PATHEXT",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TMPDIR",
        "TMP",
        "TEMP",
        "TZ",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "TERM",
        "TERMINFO",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "USERPROFILE",
        "USERNAME",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMDATA",
        "PUBLIC",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "VIRTUAL_ENV",
    }
)


def safe_subprocess_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build a conservative env: OS basics + ``AGLOOM_*`` / ``UV_*`` + optional extras."""
    out: dict[str, str] = {}
    for key, val in os.environ.items():
        ku = key.upper()
        if ku in _BASE_ENV_KEYS or key.startswith("AGLOOM_") or key.startswith("UV_"):
            out[key] = val
    if extra:
        out.update(extra)
    return out
