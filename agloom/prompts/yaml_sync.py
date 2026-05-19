"""YAML helpers for ``ai.system_prompt`` (extract / classify / persist).

CLI-specific canonical text and legacy migration live in **agloom_cli** (``yamlSystemPromptMigrate``).
The Python runtime only classifies prompts by markers and persists user edits.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_LEGACY_SYSTEM_PROMPT_MARKERS: tuple[str, ...] = (
    "built with agloom",
    "## your capabilities",
    "autonomous ai programming assistant built with agloom",
    "## guidelines",
    "## code style",
)

_CANONICAL_MARKER = "terminal workspace (agloom cli)"


def yaml_indented_block(text: str, indent: str = "    ") -> str:
    """Indent lines for a YAML ``|`` block under ``system_prompt:``."""
    return "\n".join(indent + line for line in text.strip().splitlines())


def extract_system_prompt_from_yaml(data: dict[str, Any]) -> str | None:
    """Read ``system_prompt`` from top-level or ``ai.system_prompt``."""
    ai = data.get("ai")
    if isinstance(ai, dict):
        sp = ai.get("system_prompt")
        if isinstance(sp, str) and sp.strip():
            return sp.strip()
    top = data.get("system_prompt")
    if isinstance(top, str) and top.strip():
        return top.strip()
    return None


def is_canonical_cli_system_prompt(text: str) -> bool:
    """True when YAML carries the agloom-cli workspace persona (marker-based)."""
    return _CANONICAL_MARKER in text.strip().lower()


def is_legacy_cli_system_prompt(text: str) -> bool:
    """True when the prompt looks like the pre-2025 starter template (needs migration)."""
    t = text.strip().lower()
    if _CANONICAL_MARKER in t:
        return False
    return any(marker in t for marker in _LEGACY_SYSTEM_PROMPT_MARKERS)


def is_user_tuned_system_prompt(text: str) -> bool:
    """User-edited YAML prompt — never auto-replace on startup."""
    if not text.strip():
        return False
    if is_canonical_cli_system_prompt(text):
        return False
    if is_legacy_cli_system_prompt(text):
        return False
    return True


def set_yaml_system_prompt(data: dict[str, Any], prompt: str) -> None:
    ai = data.get("ai")
    if not isinstance(ai, dict):
        ai = {}
        data["ai"] = ai
    ai["system_prompt"] = prompt.strip()
    if "system_prompt" in data:
        del data["system_prompt"]


def migrate_agloom_yaml_system_prompt(path: Path) -> bool:
    """No-op in core — legacy → canonical migration is owned by **agloom-cli** on bootstrap."""
    return False


def persist_user_system_prompt_to_yaml(path: Path, prompt: str) -> bool:
    """Write the user's ``system_prompt`` into ``ai.system_prompt`` (survives CLI restart)."""
    text = prompt.strip()
    if not text:
        return False
    data: dict[str, Any]
    if path.is_file():
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            loaded = None
        data = loaded if isinstance(loaded, dict) else {}
    else:
        data = {}
    set_yaml_system_prompt(data, text)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    except OSError:
        return False
    return True
