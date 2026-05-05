"""Configuration file loading — yaml/toml support with auto-creation."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

console = Console()

HomeDir = Path.home() / ".agloom"
DefaultConfigPath = HomeDir / "agloom.yaml"
ProjectConfigPath = Path(".agloom.yaml")

DEFAULT_CONFIG = """# agloom configuration file
# Generated on first run - edit this file to customize your environment

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
  servers: ""
  # Super-Brain MCP is always used by the CLI (https://agsuperbrain.readthedocs.io/). Optional: superbrain: { name:, command:, args: }
  superbrain: {}
  # Extra MCP servers (listed after Super-Brain unless same name replaces it)
  server_list: []

tools:
  dir: ""
  disabled: []

memory:
  enabled: true
  max_turns: 50

auto_summarize: true
summarize_threshold: 200000

skills:
  enabled: true
  max_skills: 30

rules:
  # Custom rules directory (YAML files)
  dir: ""
  # Refresh rules on each session (default: false - only refresh if missing)
  refresh: false

execution:
  max_concurrent: 4
  max_retries: 2
  retry_delay: 1.0
  llm_timeout: 120.0
  classifier_timeout: 30.0

safety:
  require_approval: false
  auto_approve: "read_file,list_directory,get_working_directory"

session:
  current_session: ""
  last_updated: ""
"""

_USER_AGLOOM_README = """# ~/.agloom — user data directory

Agloom stores cross-session data here (see **Data Storage** in the docs):

| Path | Purpose |
|------|---------|
| ``agloom.yaml`` | User configuration |
| ``sessions/`` | Session state (``<thread_id>.json``) |
| ``indexes/`` | Embeddings / smart-context project index cache |
| ``rules/`` | Cached project rules (``<project_hash>.json``) |
| ``skills/`` | Learned skills |
| ``logs/`` | Log files |

Your git repo may also contain ``./.agloom/`` (workspace notes); that is separate from this folder.

https://agloom.readthedocs.io
"""

CONFIG_HEADER = """# agloom configuration
#
# This file is auto-created on first CLI run.
# Edit this file to customize your agloom environment.
#
# For full documentation, see: https://agloom.readthedocs.io
#
# Config precedence:
#   1. CLI arguments
#   2. Project .agloom.yaml
#   3. ~/.agloom/agloom.yaml
#   4. Environment variables
#   5. Default values
"""


def ensure_config_dir() -> Path:
    """Ensure ``~/.agloom`` exists with the documented subdirectories.

    Matches the Data Storage layout: ``agloom.yaml``, ``sessions/``, ``indexes/``,
    ``rules/``, ``skills/``, ``logs/``.
    """
    HomeDir.mkdir(parents=True, exist_ok=True)
    for sub in ("sessions", "indexes", "rules", "skills", "logs"):
        (HomeDir / sub).mkdir(exist_ok=True)
    home_readme = HomeDir / "README.md"
    if not home_readme.exists():
        home_readme.write_text(_USER_AGLOOM_README.strip() + "\n", encoding="utf-8")
    return HomeDir


def create_default_config() -> dict[str, Any]:
    """Create default config and save to file if not exists."""
    if DefaultConfigPath.exists():
        return load_config(DefaultConfigPath)

    ensure_config_dir()

    with open(DefaultConfigPath, "w") as f:
        f.write(CONFIG_HEADER + "\n\n" + DEFAULT_CONFIG)

    return load_config(DefaultConfigPath)


def get_system_prompt() -> str:
    """Get system prompt from config."""
    config = load_config(None)
    return config.get("ai", {}).get("system_prompt", "") or _get_default_system_prompt()


def _get_default_system_prompt() -> str:
    """Default system prompt similar to Claude Code/Cursor."""
    return """You are an autonomous AI programming assistant built with agloom.

## Your Capabilities

You have access to tools for:
- **File operations**: read, write, list, search, create, remove files and directories
- **Shell commands**: execute commands in the terminal
- **Web search**: search the web for documentation, bugs, or solutions
- **HTTP requests**: make API calls when needed
- **Task planning**: break down complex tasks into steps
- **Working directory**: navigate and manage project context

## Guidelines

1. **Always prefer existing code** - Don't suggest rewriting unless necessary
2. **Be concise** - Give focused answers, not lengthy explanations
3. **Think step-by-step** - For complex tasks, plan before executing
4. **Use tools wisely** - Check file context before modifying
5. **Handle errors** - gracefully explain what went wrong and suggest fixes
6. **Respect user privacy** - Don't log or store sensitive data

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
- Suggest specific fixes, not just "try differently"
- Ask clarification when requirements are unclear

Remember: You're collaborating with a human. They control the session, you assist."""


def load_config(path: Path | None) -> dict[str, Any]:
    """Load configuration from yaml or toml file.

    Config search order:
    1. Current directory .agloom.yaml (project override)
    2. Home ~/.agloom/agloom.yaml (user defaults)
    3. Auto-create default config

    Config precedence (highest to lowest):
    1. CLI flags
    2. Project config file
    3. Home config file
    4. Environment variables
    5. Defaults
    """
    config_paths = []

    if path and path.exists():
        config_paths.append(path)
    elif ProjectConfigPath.exists():
        config_paths.append(ProjectConfigPath)

    if DefaultConfigPath.exists():
        config_paths.append(DefaultConfigPath)

    if not config_paths:
        return create_default_config()

    merged: dict[str, Any] = {}
    for config_path in config_paths:
        try:
            with open(config_path) as f:
                loaded = yaml.safe_load(f) or {}
            _deep_merge(merged, loaded)
        except yaml.YAMLError as e:
            console.print(f"[warning]Warning: Error parsing {config_path}: {e}[/warning]")

    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def get_thread_id(config: dict[str, Any] | None = None, auto_save: bool = True) -> str:
    """Get thread/session ID from config or generate new one.

    Priority:
    1. config.session.current_session
    2. AGLOOM_THREAD_ID env var
    3. Generate new UUID

    Args:
        config: Optional config dict
        auto_save: If True, save new session ID to config file
    """
    if config is None:
        config = create_default_config()

    session_config = config.get("session", {})
    if session_config.get("current_session"):
        return session_config["current_session"]

    if os.environ.get("AGLOOM_THREAD_ID"):
        return os.environ["AGLOOM_THREAD_ID"]

    thread_id = uuid.uuid4().hex
    if auto_save:
        save_session(thread_id)
    return thread_id


def save_session(thread_id: str, metadata: dict | None = None) -> None:
    """Save session info to config file."""
    config = create_default_config()

    if "session" not in config:
        config["session"] = {}

    config["session"]["current_session"] = thread_id
    config["session"]["last_updated"] = datetime.now().isoformat()

    with open(DefaultConfigPath, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def start_new_session(thread_id: str | None = None) -> dict[str, Any]:
    """Start a new session, creating session file."""
    import json

    if not thread_id:
        thread_id = uuid.uuid4().hex

    sessions_dir = ensure_config_dir() / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_file = sessions_dir / f"{thread_id}.json"

    session_data = {
        "id": thread_id,
        "started_at": datetime.now().isoformat(),
        "last_active": datetime.now().isoformat(),
        "turns": 0,
        "messages": [],
    }

    with open(session_file, "w") as f:
        json.dump(session_data, f, indent=2)

    config = create_default_config()
    config.setdefault("session", {})["current_session"] = thread_id
    config.setdefault("session", {})["last_updated"] = datetime.now().isoformat()

    with open(DefaultConfigPath, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    return session_data


def get_session_history(thread_id: str) -> list[dict]:
    """Get session message history."""
    import json

    if not thread_id:
        return []

    sessions_dir = ensure_config_dir() / "sessions"
    session_file = sessions_dir / f"{thread_id}.json"

    if not session_file.exists():
        return []

    with open(session_file) as f:
        session = json.load(f)

    return session.get("messages", [])


def add_to_session_history(thread_id: str, role: str, content: str) -> None:
    """Add message to session history."""
    import json

    if not thread_id:
        return

    sessions_dir = ensure_config_dir() / "sessions"
    session_file = sessions_dir / f"{thread_id}.json"

    session: dict[str, Any] = {"id": thread_id, "messages": [], "turns": 0}

    if session_file.exists():
        with open(session_file) as f:
            session = json.load(f)

    session["messages"].append(
        {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
    )
    session["last_active"] = datetime.now().isoformat()
    session["turns"] = session.get("turns", 0) + 1

    with open(session_file, "w") as f:
        json.dump(session, f, indent=2)


def resolve_model(model_id: str | None, *, interactive_providers: bool | None = None) -> Any:
    """Resolve model from ID or env var.

    CLI auto-wiring covers a subset (see ``model_resolver``). Optional extras for LangChain’s
    first-party packages live in ``pyproject.toml`` under ``[project.optional-dependencies]``.
    Integrations without their own ``langchain-*`` wheel typically need ``agloom[community]``.
    Doc index: https://docs.langchain.com/oss/python/integrations/chat

    Priority:
    1. Explicit model_id (non-``auto``) — strict; fails if the matching extra is missing.
    2. Config ``ai.model`` — if the integration is not installed, falls through.
    3. ``*_MODEL_ID`` environment variables — each is tried in order; missing extras are skipped
       (so ``OPENAI_MODEL_ID`` does not block ``GROQ_MODEL_ID`` when only ``agloom[groq]`` is installed).
    4. Auto-detect from available API keys (see ``try_resolve_llm_from_api_keys``). If several keys
       are set, a TTY prompts unless ``interactive_providers=False`` or ``AGLOOM_PROVIDER`` is set.
    """
    from .model_resolver import MissingProviderDependency, get_model, try_resolve_llm_from_api_keys

    def _is_auto(value: object | None) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip() or value.strip().lower() == "auto"
        return str(value).strip().lower() == "auto"

    # 1. Explicit override — must match installed integration.
    if model_id is not None and not _is_auto(model_id):
        return get_model(model_id.strip())

    config = create_default_config()
    cm_raw = config.get("ai", {}).get("model")
    # 2. Config file — optional fallback when e.g. ``model: gpt-4o`` but only Groq extra is installed.
    if not _is_auto(cm_raw):
        cm_str = cm_raw.strip() if isinstance(cm_raw, str) else str(cm_raw).strip()
        try:
            return get_model(cm_str)
        except MissingProviderDependency:
            pass

    # 3. Per-provider model env vars (do not let OPENAI_* alone block later providers).
    for env_key in (
        "OPENAI_MODEL_ID",
        "ANTHROPIC_MODEL_ID",
        "GROQ_MODEL_ID",
        "GOOGLE_MODEL_ID",
        "GEMINI_MODEL_ID",
        "MISTRAL_MODEL_ID",
        "XAI_MODEL_ID",
    ):
        mid = os.environ.get(env_key)
        if _is_auto(mid):
            continue
        try:
            return get_model(str(mid).strip())
        except MissingProviderDependency:
            continue

    # 4. Infer from API keys.
    return try_resolve_llm_from_api_keys(interactive=interactive_providers)


def add_to_gitignore() -> bool:
    """Add agloom config to .gitignore if not present. Returns True if modified."""
    gitignore = Path(".gitignore")

    needed = []
    if gitignore.exists():
        content = gitignore.read_text()
        if ".agloom" not in content:
            needed.append(".agloom")
        if ".agloom.yaml" not in content:
            needed.append(".agloom.yaml")
    else:
        needed = [".agloom", ".agloom.yaml"]

    if not needed:
        return False

    entries = [
        "",
        "# agloom config (local only)",
    ]
    for entry in needed:
        entries.append(entry)

    with open(gitignore, "a") as f:
        f.write("\n" + "\n".join(entries))

    return True


_DOT_AGLOOM_README = """# Project ``./.agloom/`` (workspace)

This folder under your **repo root** is optional workspace metadata (e.g. this README).
**Most agloom data lives in your user home**, not here:

``~/.agloom/`` (created on first CLI run)

- ``agloom.yaml`` — user config
- ``sessions/`` — session JSON per thread
- ``indexes/`` — embeddings / smart-context cache
- ``rules/`` — cached project rules
- ``skills/`` — learned skills
- ``logs/`` — logs

**Project overrides:** add ``.agloom.yaml`` in the repo root (merged over ``~/.agloom/agloom.yaml``).

**Multiple API keys:** set ``AGLOOM_PROVIDER`` to ``openai``, ``groq``, ``anthropic``, ``google``, ``mistralai``, or ``xai``.

Docs: https://agloom.readthedocs.io
"""


def ensure_project_dot_agloom(project_root: Path) -> None:
    """Create ``<project>/.agloom/`` so local CLI state matches documented/gitignored paths.

    Home config lives under ``~/.agloom/``; project scope uses ``./.agloom/`` for workspace-local files.
    """
    ag_dir = project_root / ".agloom"
    ag_dir.mkdir(parents=True, exist_ok=True)
    readme = ag_dir / "README.md"
    if not readme.exists():
        readme.write_text(_DOT_AGLOOM_README.strip() + "\n", encoding="utf-8")


def ensure_config_ready() -> dict[str, Any]:
    """Ensure config is ready: create if needed, add to gitignore."""
    config = create_default_config()
    add_to_gitignore()
    return config
