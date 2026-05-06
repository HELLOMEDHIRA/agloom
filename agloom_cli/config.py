"""Configuration file loading — yaml/toml support with auto-creation."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generator

import yaml
from rich.console import Console

console = Console()

HomeDir = Path.home() / ".agloom"
_cli_storage_dir: Path | None = None
DefaultConfigPath = HomeDir / "agloom.yaml"
ProjectConfigPath = Path(".agloom.yaml")

_STORAGE_README = """# Agloom data (this directory)

The **agloom CLI** stores config and cached state **only** here — ``<project>/.agloom/`` — not under your user profile.

| Path | Purpose |
|------|---------|
| ``agloom.yaml`` | Configuration (optional ``ai.api_keys``: env-style secrets for local use) |
| ``sessions/`` | Session state |
| ``checkpoints.sqlite`` | LangGraph checkpoints (CLI session resume when memory is on) |
| ``graph_store.sqlite`` | LangGraph store backing long-term / session memory |
| ``rules/`` | Cached project rules |
| ``skills/`` | Skills (``SKILL.md`` trees, including learned skills) |
| ``tool_allowlist.json`` (or ``safety.allowlist_file`` basename) | Per-project HITL allowlist; lives only under this folder |

Optional: a ``.agloom.yaml`` in the **project root** (parent of this folder) is merged on top of ``agloom.yaml``; later files override earlier ones.

If you use ``agloom_cli`` from Python without ``set_cli_project_root``, the first touch creates ``~/.agloom`` with the same layout instead.

https://agloom.readthedocs.io
"""


def storage_dir() -> Path:
    """Root directory for config, sessions, rules, and skills.

    When the CLI has bound a project via ``set_cli_project_root``, this is
    ``<project>/.agloom``. Otherwise (library / tests) it falls back to ``~/.agloom``.
    """
    return _cli_storage_dir if _cli_storage_dir is not None else HomeDir


def set_cli_project_root(project_root: Path) -> Path:
    """Bind all CLI storage to ``<project_root>/.agloom`` and ensure layout exists."""
    global _cli_storage_dir, DefaultConfigPath

    root = project_root.resolve()
    ag = root / ".agloom"
    ag.mkdir(parents=True, exist_ok=True)
    for sub in ("sessions", "rules", "skills"):
        (ag / sub).mkdir(exist_ok=True)

    _cli_storage_dir = ag
    DefaultConfigPath = ag / "agloom.yaml"
    _migrate_legacy_home_config(ag)

    readme = ag / "README.md"
    if not readme.exists():
        readme.write_text(_STORAGE_README.strip() + "\n", encoding="utf-8")
    return ag


def _migrate_legacy_home_config(project_agloom: Path) -> None:
    """Copy ``~/.agloom/agloom.yaml`` into the project store if the latter is missing."""
    dest = project_agloom / "agloom.yaml"
    if dest.exists():
        return
    legacy = HomeDir / "agloom.yaml"
    if legacy.exists():
        try:
            shutil.copy2(legacy, dest)
        except OSError:
            pass


def config_yaml_path() -> Path:
    """Path to the active ``agloom.yaml`` (under ``storage_dir()``)."""
    return storage_dir() / "agloom.yaml"


_CLEANUP_DIR_NAMES = (".agloom", ".agsuperbrain")


def list_project_cleanup_dirs(project_root: Path) -> list[Path]:
    """Return existing ``.agloom`` and ``.agsuperbrain`` directories under *project_root*."""
    root = project_root.resolve()
    found: list[Path] = []
    for name in _CLEANUP_DIR_NAMES:
        p = (root / name).resolve(strict=False)
        if not p.is_dir():
            continue
        try:
            p.relative_to(root)
        except ValueError:
            continue
        if p.name != name:
            continue
        found.append(p)
    return found


def remove_project_cleanup_dirs(project_root: Path) -> list[Path]:
    """Remove ``.agloom`` and ``.agsuperbrain`` under *project_root*. Returns removed paths."""
    global _cli_storage_dir, DefaultConfigPath

    removed: list[Path] = []
    for p in list_project_cleanup_dirs(project_root):
        shutil.rmtree(p)
        removed.append(p)

    if _cli_storage_dir is not None and removed:
        try:
            cur = _cli_storage_dir.resolve()
            if any(cur == r.resolve() for r in removed):
                _cli_storage_dir = None
                DefaultConfigPath = HomeDir / "agloom.yaml"
        except OSError:
            pass
    return removed


DEFAULT_CONFIG = """# agloom configuration file
# Generated on first run - edit this file to customize your environment

ai:
  name: agloom
  # Default when you run ``agloom`` without ``-m``. Override per run: ``agloom -m llama-3.3-70b-versatile``
  model: auto
  # Optional explicit backend for ambiguous ids (e.g. meta-llama/...): groq | ollama | vllm | litellm | openrouter | openai | ...
  # Ignored when you pass ``-m`` unless you also pass ``--provider`` (CLI wins).
  # provider: groq
  # Base URL for local ollama / OpenAI-compatible vLLM (defaults: localhost — see docs).
  # base_url: ""
  # Optional API keys (local / project-only — use the same names as environment variables).
  # Applied only while the CLI resolves the chat model; LangChain integrations read them from the process env.
  # Prefer env vars in CI; keep this file out of git if it contains secrets.
  # api_keys:
  #   OPENAI_API_KEY: sk-...
  #   GROQ_API_KEY: gsk-...
  #   ANTHROPIC_API_KEY: sk-ant-...
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
    3. Think step-by-step internally — in the **final reply**, summarize outcomes; do not narrate "Step 1/2" after tools already ran
    4. Use tools wisely - Check file context before modifying
    5. Handle errors - gracefully explain what went wrong
    6. Respect user privacy - Don't log or store sensitive data

    ## Terminal agent style (CLI)

    - After a successful tool action, confirm in **1–3 short sentences** (paths, result). Do **not** teach how to do what you already did.
    - The session UI shows tool traces; avoid duplicating tool payloads or tutorial markdown unless asked.

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
  # Super-Brain MCP is always used by the CLI (https://agsuperbrain.readthedocs.io/). Default args: [-u, -m, agsuperbrain, mcp]. Optional: superbrain: { name:, command:, args: }
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
  require_approval: true
  auto_approve: "read_file,list_directory,get_working_directory"
  # HITL "always allow" is stored only under project .agloom/ (basename only; default tool_allowlist.json).
  # When true (default): if that file exists, only its "tools" list applies — safety.auto_approve is ignored.
  # When false: yaml auto_approve and JSON tools are unioned. If the file does not exist yet, yaml applies alone.
  allowlist_strict_tools: true
  allowlist_file: ""
  # When true, "Always allow" during HITL appends to the allowlist file under .agloom
  persist_tool_allowlist: true

session:
  current_session: ""
  last_updated: ""
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
#   2. Explicit -c/--config file
#   3. Project-root .agloom.yaml
#   4. <project>/.agloom/agloom.yaml (or ~/.agloom/agloom.yaml if no CLI project)
#   5. Environment variables
#   6. Default values
"""


def ensure_storage_layout() -> Path:
    """Ensure ``storage_dir()`` exists with the documented subdirectories."""
    root = storage_dir()
    root.mkdir(parents=True, exist_ok=True)
    for sub in ("sessions", "rules", "skills"):
        (root / sub).mkdir(exist_ok=True)
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(_STORAGE_README.strip() + "\n", encoding="utf-8")
    return root


def ensure_config_dir() -> Path:
    """Backward-compatible alias for :func:`ensure_storage_layout`."""
    return ensure_storage_layout()


def create_default_config() -> dict[str, Any]:
    """Create default config and save to file if not exists."""
    ensure_storage_layout()
    cfgp = config_yaml_path()
    if cfgp.exists():
        with open(cfgp, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    with open(cfgp, "w", encoding="utf-8") as f:
        f.write(CONFIG_HEADER + "\n\n" + DEFAULT_CONFIG)

    with open(cfgp, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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
3. **Plan internally** — for complex tasks, think before acting; in your **final reply**, give outcomes, not a "Step 1 / Step 2" tutorial after tools already ran
4. **Use tools wisely** - Check file context before modifying
5. **Handle errors** - gracefully explain what went wrong and suggest fixes
6. **Respect user privacy** - Don't log or store sensitive data

## Terminal agent style (agloom CLI)

- You run in a **coding-agent shell** (like Cursor / Claude Code). When tools succeeded, reply **briefly**: what changed (paths, commands), errors if any, optional one-line follow-up.
- **Never** re-explain how to perform work you already completed with tools. Do not dump long tool JSON or full file contents unless the user asked to review them.

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
    """Load configuration from YAML files and merge.

    Files are merged in order; later files override earlier keys (see ``_deep_merge``).

    1. ``storage_dir()/agloom.yaml`` if it exists
    2. Project-root ``.agloom.yaml`` if it exists (and is not the same path)
    3. Explicit ``path`` if given and exists

    If no files exist, :func:`create_default_config` is used.
    """
    storage_yaml = config_yaml_path()
    seen: set[Path] = set()
    config_paths: list[Path] = []

    def _append(cfg_path: Path) -> None:
        try:
            key = cfg_path.resolve()
        except OSError:
            key = cfg_path
        if key in seen or not cfg_path.exists():
            return
        seen.add(key)
        config_paths.append(cfg_path)

    _append(storage_yaml)
    _append(ProjectConfigPath)
    if path is not None:
        _append(path)

    if not config_paths:
        return create_default_config()

    merged: dict[str, Any] = {}
    for config_path in config_paths:
        try:
            with open(config_path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            _deep_merge(merged, loaded)
        except yaml.YAMLError as e:
            console.print(f"[warning]Warning: Error parsing {config_path}: {e}[/warning]")

    return merged


def collect_loaded_config_paths(explicit: Path | None = None) -> list[Path]:
    """Config files that :func:`load_config` merges, in order (existing files only)."""
    storage_yaml = config_yaml_path()
    seen: set[Path] = set()
    paths: list[Path] = []

    def _append(cfg_path: Path) -> None:
        try:
            key = cfg_path.resolve()
        except OSError:
            key = cfg_path
        if key in seen or not cfg_path.is_file():
            return
        seen.add(key)
        paths.append(cfg_path)

    _append(storage_yaml)
    _append(ProjectConfigPath)
    if explicit is not None:
        _append(explicit)
    return paths


def config_source_fingerprints(explicit: Path | None = None) -> list[dict[str, Any]]:
    """Per-file SHA-256 and mtime for each config layer (for session audit metadata)."""
    out: list[dict[str, Any]] = []
    for p in collect_loaded_config_paths(explicit):
        raw = p.read_bytes()
        st = p.stat()
        out.append(
            {
                "path": str(p.resolve()),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "mtime_utc": datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(),
            }
        )
    return out


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


@contextmanager
def use_ai_api_key_overlay(ai: dict[str, Any]) -> Generator[None, None, None]:
    """Temporarily set process env vars from ``ai.api_keys`` for LangChain SDK compatibility."""
    raw = ai.get("api_keys")
    if not isinstance(raw, dict):
        yield
        return
    overlay: dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or v is None:
            continue
        ks = k.strip()
        vs = str(v).strip()
        if ks and vs:
            overlay[ks] = vs
    if not overlay:
        yield
        return
    previous: dict[str, str | None] = {k: os.environ.get(k) for k in overlay}
    try:
        for k, v in overlay.items():
            os.environ[k] = v
        yield
    finally:
        for k, old in previous.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


_SESSION_UUID_HYPHEN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_SESSION_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")
_SESSION_SAFE_CUSTOM = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def normalize_cli_session_id(raw: str) -> str:
    """Normalize and validate a session / thread id for CLI and storage filenames.

    Accepts 32-char hex (as produced by ``uuid.uuid4().hex``), hyphenated UUIDs
    (normalized to lowercase hex without hyphens), or 1–128 ASCII letters,
    digits, underscores, or hyphens.

    Raises:
        ValueError: empty, too long, path-like input, or disallowed characters.
    """
    s = raw.strip()
    if not s:
        raise ValueError("Session id is empty.")
    if len(s) > 128:
        raise ValueError("Session id must be at most 128 characters.")
    if ".." in s or "/" in s or "\\" in s:
        raise ValueError("Session id must not contain path segments (/ , \\, or ..).")
    if _SESSION_UUID_HYPHEN.fullmatch(s):
        return s.replace("-", "").lower()
    if _SESSION_HEX32.fullmatch(s):
        return s.lower()
    if _SESSION_SAFE_CUSTOM.fullmatch(s):
        return s
    raise ValueError(
        "Session id must be 32 hex characters, a hyphenated UUID, "
        "or 1–128 ASCII letters, digits, underscores, or hyphens."
    )


def session_record_path(thread_id: str) -> Path:
    """Path to ``sessions/<thread_id>.json`` under the active storage root."""
    return ensure_storage_layout() / "sessions" / f"{thread_id}.json"


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
        return normalize_cli_session_id(str(session_config["current_session"]))

    env_tid = os.environ.get("AGLOOM_THREAD_ID")
    if env_tid:
        return normalize_cli_session_id(env_tid)

    thread_id = uuid.uuid4().hex
    if auto_save:
        save_session(thread_id)
    return thread_id


def save_session(thread_id: str, metadata: dict | None = None) -> None:
    """Save session info to config file."""
    thread_id = normalize_cli_session_id(thread_id)
    config = create_default_config()

    if "session" not in config:
        config["session"] = {}

    config["session"]["current_session"] = thread_id
    config["session"]["last_updated"] = datetime.now().isoformat()

    with open(config_yaml_path(), "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def start_new_session(
    thread_id: str | None = None,
    *,
    run_metadata: dict[str, Any] | None = None,
    update_config_current_session: bool = True,
) -> dict[str, Any]:
    """Create or update the session JSON and optionally record ``last_run`` audit metadata.

    If the session file already exists, ``messages``, ``turns``, and other fields are
    preserved; ``last_active`` and ``last_run`` are updated.

    If ``update_config_current_session`` is False, ``agloom.yaml``'s ``session.current_session``
    is left unchanged (CLI uses this for auto-generated sessions).
    """
    import json

    if not thread_id:
        thread_id = uuid.uuid4().hex
    else:
        thread_id = normalize_cli_session_id(thread_id)

    sessions_dir = ensure_storage_layout() / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_file = sessions_dir / f"{thread_id}.json"

    now = datetime.now(UTC).isoformat()

    if session_file.exists():
        with open(session_file, encoding="utf-8") as f:
            session_data: dict[str, Any] = json.load(f)
        session_data.setdefault("id", thread_id)
        session_data["last_active"] = now
        if run_metadata is not None:
            session_data["last_run"] = run_metadata
    else:
        session_data = {
            "id": thread_id,
            "started_at": now,
            "last_active": now,
            "turns": 0,
            "messages": [],
        }
        if run_metadata is not None:
            session_data["last_run"] = run_metadata

    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2)

    if update_config_current_session:
        config = create_default_config()
        config.setdefault("session", {})["current_session"] = thread_id
        config.setdefault("session", {})["last_updated"] = datetime.now().isoformat()

        with open(config_yaml_path(), "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    return session_data


def get_session_history(thread_id: str) -> list[dict]:
    """Get session message history."""
    import json

    if not thread_id:
        return []

    thread_id = normalize_cli_session_id(thread_id)
    sessions_dir = ensure_storage_layout() / "sessions"
    session_file = sessions_dir / f"{thread_id}.json"

    if not session_file.exists():
        return []

    with open(session_file, encoding="utf-8") as f:
        session = json.load(f)

    return session.get("messages", [])


def add_to_session_history(thread_id: str, role: str, content: str) -> None:
    """Add message to session history."""
    import json

    if not thread_id:
        return

    thread_id = normalize_cli_session_id(thread_id)
    sessions_dir = ensure_storage_layout() / "sessions"
    session_file = sessions_dir / f"{thread_id}.json"

    session: dict[str, Any] = {"id": thread_id, "messages": [], "turns": 0}

    if session_file.exists():
        with open(session_file, encoding="utf-8") as f:
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


def resolve_model(
    model_id: str | None,
    *,
    config: dict[str, Any] | None = None,
    interactive_providers: bool | None = None,
    provider: str | None = None,
    base_url: str | None = None,
    merge_yaml_provider: bool = True,
) -> Any:
    """Resolve model from ID or env var.

    CLI auto-wiring covers a subset (see ``model_resolver``). Optional extras for LangChain’s
    first-party packages live in ``pyproject.toml`` under ``[project.optional-dependencies]``.
    Integrations without their own ``langchain-*`` wheel typically need ``agloom[community]``.
    Doc index: https://docs.langchain.com/oss/python/integrations/chat

    When *config* is omitted, :func:`load_config` is used so project ``.agloom.yaml`` layers apply.
    ``ai.api_keys`` in that merged config is applied temporarily (process env) while resolving the
    model so all LangChain integrations see standard ``*_API_KEY`` variables.

    Priority:
    1. Explicit model_id (non-``auto``) — strict; fails if the matching extra is missing.
       Uses ``provider`` / ``base_url`` kwargs when passed (CLI overrides config).
    2. Config ``ai.model`` with optional ``ai.provider`` and ``ai.base_url`` — falls through on
       missing integration.
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

    def _cfg_provider_base(ai: dict[str, Any]) -> tuple[str | None, str | None]:
        raw_p = ai.get("provider")
        raw_b = ai.get("base_url")
        p = raw_p.strip() if isinstance(raw_p, str) and raw_p.strip() else None
        b = raw_b.strip() if isinstance(raw_b, str) and raw_b.strip() else None
        return p, b

    merged_conf = load_config(None) if config is None else config
    ai_cfg = merged_conf.get("ai", {}) if isinstance(merged_conf.get("ai"), dict) else {}
    cfg_prov, cfg_base = _cfg_provider_base(ai_cfg)

    eff_prov = cfg_prov if merge_yaml_provider else None
    eff_base = cfg_base if merge_yaml_provider else None
    merged_provider = (provider or eff_prov or "").strip().lower() or None
    merged_base = (base_url or eff_base or "").strip() or None

    with use_ai_api_key_overlay(ai_cfg):
        # 1. Explicit override — must match installed integration.
        if model_id is not None and not _is_auto(model_id):
            return get_model(model_id.strip(), provider=merged_provider, base_url=merged_base)

        cm_raw = ai_cfg.get("model")
        # 2. Config file — optional fallback when e.g. ``model: gpt-4o`` but only Groq extra is installed.
        if not _is_auto(cm_raw):
            cm_str = cm_raw.strip() if isinstance(cm_raw, str) else str(cm_raw).strip()
            try:
                return get_model(cm_str, provider=merged_provider, base_url=merged_base)
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
                return get_model(str(mid).strip(), provider=merged_provider, base_url=merged_base)
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


def ensure_config_ready() -> dict[str, Any]:
    """Ensure config is ready: create if needed, add to gitignore."""
    config = create_default_config()
    add_to_gitignore()
    return config


def merge_ai_into_storage_yaml(ai_updates: dict[str, Any]) -> None:
    """Deep-merge *ai_updates* into ``storage_dir()/agloom.yaml`` under the ``ai`` key."""
    path = config_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError:
            data = {}
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("ai", {})
    if not isinstance(data["ai"], dict):
        data["ai"] = {}
    _deep_merge(data["ai"], ai_updates)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(
            data,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
