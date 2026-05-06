"""Configuration file loading — yaml/toml support with auto-creation."""

from __future__ import annotations

import copy
import hashlib
import os
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
| ``agloom.yaml`` | Configuration (``ai.api_keys`` merged into process env for the CLI session) |
| ``sessions/`` | Per session: ``<id>.json`` (history, ``model_binding``) and ``<id>.yaml`` (``ai:`` + optional ``safety:`` e.g. ``tool_allowlist``) |
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
  # Optional API keys (exact env var names, e.g. GROQ_API_KEY). Listed keys are written into the
  # process environment and override any existing export for that variable (session/project YAML wins).
  # Prefer env-only in CI; session YAML can snapshot keys when saving from the wizard.
  # api_keys:
  #   NVIDIA_API_KEY: nvapi-...
  #   OPENAI_API_KEY: sk-...
  #   GROQ_API_KEY: gsk-...
  #   ANTHROPIC_API_KEY: sk-ant-...
  # Curated integrations — typical ``api_keys`` env names + routing (see model_resolver.get_model):
  #   openai: OPENAI_API_KEY; optional base_url (Azure/custom). llm keys are filtered to that client
  #     (``timeout`` → ``request_timeout``, ``max_completion_tokens`` → ``max_tokens``, …).
  #   anthropic: ANTHROPIC_API_KEY; llm: ``stop`` → ``stop_sequences``, ``timeout`` → ``default_request_timeout``.
  #   google / gemini: GOOGLE_API_KEY or GEMINI_API_KEY; llm: ``max_tokens``/``max_completion_tokens`` → ``max_output_tokens``.
  #   mistralai: MISTRAL_API_KEY
  #   groq: GROQ_API_KEY
  #   xai: XAI_API_KEY
  #   ollama: no key; base_url or OLLAMA_HOST / OLLAMA_BASE_URL
  #   vllm: base_url; OPENAI_API_KEY or VLLM_API_KEY optional (often EMPTY)
  #   litellm: model litellm:upstream/model; OPENAI_API_KEY default; base_url → api_base
  #   openrouter: OPENROUTER_API_KEY; cerebras: CEREBRAS_API_KEY; nvidia: NVIDIA_API_KEY
  #   lc: / init: / other slugs: LangChain ``init_chat_model`` — see upstream docs.
  # Endpoint routing: base_url merges when --base-url omitted. provider merges when CLI model omitted.
  # base_url: http://127.0.0.1:11434
  # Client / sampling options: defaults match ``_LLM_YAML_DEFAULTS`` (:func:`baseline_llm_params`).
  # Change any value; ``null`` keeps optional fields out of provider requests (no baseline for that key).
  llm:
    temperature: 0
    top_p: 1.0
    top_k: null
    max_tokens: null
    max_completion_tokens: null
    frequency_penalty: 0.0
    presence_penalty: 0.0
    timeout: null
    max_retries: 2
    seed: null
    stop: null
    n: null
    logprobs: null
    reasoning_effort: null
    disable_reasoning: null
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

# Optional confined workspace (see ``agloom_cli.tools.LocalSandbox``). Not wired into default CLI tools yet.
sandbox:
  enabled: false
  root: ""

safety:
  require_approval: true
  # Comma list or YAML list. Include ``tools`` to pause before every tool (default when unset and require_approval).
  interrupt_before_tools: "tools"
  # Comma-separated tool names that skip the approval modal (empty = prompt for all unless allowlisted).
  auto_approve: ""
  # Optional: always-allowed tools from project config (union with ``sessions/<id>.yaml`` ``safety.tool_allowlist``).
  # Session file entries are merged here; YAML ``tool_allowlist`` is always honored even when allowlist_strict_tools is true.
  tool_allowlist: []
  # HITL "always allow" also writes ``sessions/<id>.yaml`` when using the CLI. JSON under .agloom is optional extra.
  # When true (default): if that file exists, only its "tools" list applies — safety.auto_approve is ignored.
  # When false: yaml auto_approve and JSON tools are unioned. If the file does not exist yet, yaml applies alone.
  allowlist_strict_tools: true
  allowlist_file: ""
  # When true, "Always allow" during HITL appends to session YAML and the allowlist JSON under .agloom
  persist_tool_allowlist: true

session:
  current_session: ""
  last_updated: ""
  # Per-thread overrides: ``<storage>/sessions/<thread_id>.yaml`` (optional). Same ``ai:`` keys as
  # this file — ``model``, ``provider``, ``base_url``, ``llm`` (timeout, max_retries, temperature,
  # top_p, max_tokens, …), ``api_keys``. Optional ``safety:`` (e.g. ``tool_allowlist``) is merged
  # with project ``safety`` for that thread. Session YAML wins over project for that thread. JSON keeps
  # ``model_binding`` + history; YAML is where you set per-session endpoints and sampling.
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


def config_layer_fingerprint(path: Path) -> dict[str, Any] | None:
    """Single-file fingerprint for optional layers (e.g. per-session YAML)."""
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes()
        st = path.stat()
    except OSError:
        return None
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "mtime_utc": datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(),
    }


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


_LLM_YAML_PARAM_KEYS: frozenset[str] = frozenset(
    {
        "temperature",
        "top_p",
        "top_k",
        "max_tokens",
        "max_completion_tokens",
        "frequency_penalty",
        "presence_penalty",
        "timeout",
        "max_retries",
        "seed",
        "stop",
        "n",
        "logprobs",
        "reasoning_effort",
        "disable_reasoning",
    }
)

# Canonical defaults for ``ai.llm`` (API-style defaults where known; ``None`` = omit from requests).
# Merged under user/session YAML so every knob has a defined baseline; edit YAML to override.
_LLM_YAML_DEFAULTS: dict[str, Any] = {
    "temperature": 0,
    "top_p": 1.0,
    "top_k": None,
    "max_tokens": None,
    "max_completion_tokens": None,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "timeout": None,
    "max_retries": 2,
    "seed": None,
    "stop": None,
    "n": None,
    "logprobs": None,
    "reasoning_effort": None,
    "disable_reasoning": None,
}


def baseline_llm_params() -> dict[str, Any]:
    """Return non-``None`` entries from :data:`_LLM_YAML_DEFAULTS` (applied before ``ai.llm`` in YAML)."""
    return {k: v for k, v in _LLM_YAML_DEFAULTS.items() if v is not None}


def llm_params_from_ai_config(ai: dict[str, Any]) -> dict[str, Any]:
    """Return kwargs for :func:`~agloom_cli.model_resolver.get_model` from ``ai.llm``."""
    raw = ai.get("llm")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            continue
        key = k.strip()
        if key not in _LLM_YAML_PARAM_KEYS:
            continue
        if v is None:
            continue
        out[key] = v
    return out


def _ai_yaml_provider_base(ai: dict[str, Any]) -> tuple[str | None, str | None]:
    raw_p = ai.get("provider")
    raw_b = ai.get("base_url")
    p = raw_p.strip() if isinstance(raw_p, str) and raw_p.strip() else None
    b = raw_b.strip() if isinstance(raw_b, str) and raw_b.strip() else None
    return p, b


def merged_provider_base_for_resolve(
    ai_cfg: dict[str, Any],
    *,
    provider: str | None,
    base_url: str | None,
    merge_yaml_provider: bool,
) -> tuple[str | None, str | None]:
    """Compute ``provider`` / ``base_url`` exactly as :func:`resolve_model` passes to ``get_model``.

    ``ai.provider`` from config is only merged when *merge_yaml_provider* is True (same as legacy
    ``merge_yaml_provider=model is None``): avoids yaml backend fighting an explicit ``-m groq:…`` prefix.

    ``ai.base_url`` is **always** merged when the caller does not pass *base_url*, so Ollama / vLLM /
    OpenAI-compatible / LiteLLM endpoints from project or ``sessions/<id>.yaml`` still apply with
    ``agloom -m ollama:…`` or ``-m vllm:…``.
    """
    cfg_prov, cfg_base = _ai_yaml_provider_base(ai_cfg)
    eff_prov = cfg_prov if merge_yaml_provider else None
    eff_base = cfg_base
    merged_provider = (provider or eff_prov or "").strip().lower() or None
    merged_base = (base_url or eff_base or "").strip() or None
    return merged_provider, merged_base


def merged_llm_params_for_resolve(
    ai_cfg: dict[str, Any],
    *,
    llm_frozen: dict[str, Any] | None = None,
    llm_param_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build LLM option kwargs passed into ``get_model`` / ``try_resolve_llm_from_api_keys``.

    Order: :func:`baseline_llm_params` → ``ai.llm`` from config (if not frozen) → *llm_frozen* →
    *llm_param_overrides*. Keys with value ``None`` are dropped so integrations only receive
    meaningful options. Unknown YAML keys remain ignored (see :data:`_LLM_YAML_PARAM_KEYS`).
    """
    base = baseline_llm_params()
    if llm_frozen is not None:
        merged = {**base, **llm_frozen, **(llm_param_overrides or {})}
    else:
        merged = {**base, **llm_params_from_ai_config(ai_cfg), **(llm_param_overrides or {})}
    merged = {k: v for k, v in merged.items() if v is not None}
    merged.setdefault("temperature", 0)
    return merged


def read_session_model_binding(thread_id: str) -> dict[str, Any] | None:
    """Load ``model_binding`` from ``sessions/<id>.json`` if present.

    The CLI writes this on each run so ``agloom --session <id>`` can reopen the same backend
    (model id, provider/base_url routing, and merged decoding kwargs) without repeating ``-m``.
    """
    import json

    tid = normalize_cli_session_id(thread_id)
    path = session_record_path(tid)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("model_binding")
    if not isinstance(raw, dict):
        return None
    return raw


def session_model_binding_is_usable(binding: dict[str, Any]) -> bool:
    """Return True if *binding* has a concrete model string (not empty / ``auto``)."""
    em = binding.get("effective_model")
    if not isinstance(em, str) or not em.strip():
        return False
    if em.strip().lower() == "auto":
        return False
    return True


def session_config_yaml_path(thread_id: str) -> Path:
    """Path to per-thread overrides: ``sessions/<id>.yaml`` (next to ``sessions/<id>.json``).

    :func:`start_new_session` creates this file on first write if it is missing (``ai: {}`` or a
    snapshot from ``model_binding``). :func:`merge_ai_into_session_yaml` updates the same file.
    """
    tid = normalize_cli_session_id(thread_id)
    return ensure_storage_layout() / "sessions" / f"{tid}.yaml"


def session_ai_updates_from_model_binding(binding: dict[str, Any]) -> dict[str, Any]:
    """Turn JSON ``model_binding`` into ``ai`` keys for session YAML (deep-copy ``llm``)."""
    out: dict[str, Any] = {}
    em = binding.get("effective_model")
    if isinstance(em, str) and em.strip():
        out["model"] = em.strip()
    mp = binding.get("provider")
    if isinstance(mp, str) and mp.strip():
        out["provider"] = mp.strip()
    # Always snapshot ``base_url`` (``null`` = SDK / provider default host — was omitted before).
    bu = binding.get("base_url")
    if isinstance(bu, str) and bu.strip():
        out["base_url"] = bu.strip()
    else:
        out["base_url"] = None
    raw_keys = binding.get("api_keys")
    if isinstance(raw_keys, dict) and raw_keys:
        out["api_keys"] = copy.deepcopy(raw_keys)
    else:
        out["api_keys"] = None
    llm = binding.get("llm")
    if isinstance(llm, dict) and llm:
        out["llm"] = copy.deepcopy(llm)
    return out


def _ensure_session_yaml_sidecar(thread_id: str, *, model_binding: dict[str, Any] | None) -> None:
    """Create ``sessions/<id>.yaml`` if missing so every session has a YAML sibling to the JSON."""
    tid = normalize_cli_session_id(thread_id)
    path = session_config_yaml_path(tid)
    if not path.is_file():
        if model_binding:
            merge_ai_into_session_yaml(tid, session_ai_updates_from_model_binding(model_binding))
        else:
            merge_ai_into_session_yaml(tid, {})
        return
    if not model_binding:
        return
    fragment = load_session_config_yaml(tid)
    ai = fragment.get("ai", {}) if isinstance(fragment.get("ai"), dict) else {}
    snap = session_ai_updates_from_model_binding(model_binding)
    backfill: dict[str, Any] = {}
    if "base_url" not in ai:
        backfill["base_url"] = snap.get("base_url")
    if "provider" not in ai and isinstance(snap.get("provider"), str) and snap["provider"].strip():
        backfill["provider"] = snap["provider"].strip()
    sk = snap.get("api_keys")
    if "api_keys" not in ai and isinstance(sk, dict) and sk:
        backfill["api_keys"] = copy.deepcopy(sk)
    if backfill:
        merge_ai_into_session_yaml(tid, backfill)


def load_session_config_yaml(thread_id: str) -> dict[str, Any]:
    """Load optional session YAML.

    The ``ai:`` subtree is merged by :func:`build_working_ai_for_thread`; the ``safety:`` subtree by
    :func:`build_working_safety_for_thread`.
    """
    path = session_config_yaml_path(thread_id)
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return raw if isinstance(raw, dict) else {}


def build_working_ai_for_thread(cfg: dict[str, Any], thread_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge project ``cfg['ai']`` with ``sessions/<id>.yaml`` → ``ai`` (session wins per key).

    Returns ``(working_ai, session_ai_only)`` where *session_ai_only* is the ``ai`` dict from the
    session file (empty if no file) — used to prefer session YAML over JSON ``model_binding``.
    """
    import copy

    project_ai = cfg.get("ai", {}) if isinstance(cfg.get("ai"), dict) else {}
    fragment = load_session_config_yaml(thread_id)
    session_ai = fragment.get("ai", {}) if isinstance(fragment.get("ai"), dict) else {}
    working = copy.deepcopy(project_ai)
    _deep_merge(working, session_ai)
    return working, session_ai


def normalized_safety_tool_allowlist(raw: Any) -> list[str]:
    """Normalize ``safety.tool_allowlist`` / ``allowlist_tools`` from YAML or comma-separated strings."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    return []


def build_working_safety_for_thread(cfg: dict[str, Any], thread_id: str) -> dict[str, Any]:
    """Merge project ``cfg['safety']`` with ``sessions/<id>.yaml`` ``safety:`` (session deep-merges on top).

    ``tool_allowlist`` / ``allowlist_tools`` from project and session are **unioned** so session
    additions always apply alongside project entries.
    """
    project = cfg.get("safety")
    if not isinstance(project, dict):
        project = {}
    out = copy.deepcopy(project)
    fragment = load_session_config_yaml(thread_id)
    sess = fragment.get("safety")
    if not isinstance(sess, dict) or not sess:
        return out
    sess = copy.deepcopy(sess)
    proj_tl = normalized_safety_tool_allowlist(out.get("tool_allowlist") or out.get("allowlist_tools"))
    sess_tl = normalized_safety_tool_allowlist(sess.get("tool_allowlist") or sess.get("allowlist_tools"))
    for k in ("tool_allowlist", "allowlist_tools"):
        sess.pop(k, None)
    _deep_merge(out, sess)
    merged_tl = sorted(set(proj_tl) | set(sess_tl))
    if merged_tl:
        out["tool_allowlist"] = merged_tl
    else:
        out.pop("tool_allowlist", None)
    return out


def coerce_interrupt_before_tools_list(raw: Any, *, require_approval: bool) -> list[str] | None:
    """Normalize ``interrupt_before_tools`` from CLI string, YAML list, or ``None``.

    When *require_approval* is True and *raw* is unset or blank, returns ``[\"tools\"]`` (pause before
    every tool). When *require_approval* is False and *raw* is unset, returns ``None``. An explicit
    empty YAML list ``[]`` yields ``[]`` (no L2 tool interrupts).
    """
    if raw is None:
        return ["tools"] if require_approval else None
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    s = str(raw).strip()
    if not s:
        return ["tools"] if require_approval else None
    return [t.strip() for t in s.split(",") if t.strip()]


def merge_ai_into_session_yaml(thread_id: str, ai_updates: dict[str, Any]) -> None:
    """Deep-merge *ai_updates* into ``sessions/<id>.yaml`` under ``ai`` (session-scoped defaults)."""
    path = session_config_yaml_path(thread_id)
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


def merge_ai_api_keys_into_process_env(ai: dict[str, Any]) -> None:
    """Copy ``ai.api_keys`` into :func:`os.environ` for LangChain and SDKs.

    Each key present under ``ai.api_keys`` **overwrites** the process environment for that
    variable name (project or session YAML wins over any pre-existing export). Keys not listed
    in YAML are left unchanged.

    ``api_keys_override`` is legacy and ignored; listing a key under ``api_keys`` is sufficient.

    Called when resolving the model and at CLI startup so keys remain available for the
    whole run (LLM calls happen after model construction).
    """
    raw = ai.get("api_keys")
    if not isinstance(raw, dict):
        return
    for k, v in raw.items():
        if not isinstance(k, str) or v is None:
            continue
        ks = k.strip()
        vs = str(v).strip()
        if not ks or not vs:
            continue
        os.environ[ks] = vs


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


def merge_tool_allowlist_into_session_yaml(thread_id: str, tool_name: str) -> None:
    """Append *tool_name* to ``sessions/<id>.yaml`` under ``safety.tool_allowlist`` (create file if needed)."""
    tid = normalize_cli_session_id(thread_id)
    path = session_config_yaml_path(tid)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            data = {}
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("safety", {})
    if not isinstance(data["safety"], dict):
        data["safety"] = {}
    tools = normalized_safety_tool_allowlist(data["safety"].get("tool_allowlist"))
    tn = (tool_name or "").strip()
    if tn and tn not in tools:
        tools.append(tn)
    data["safety"]["tool_allowlist"] = tools
    path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
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
    config["session"]["last_updated"] = datetime.now(UTC).isoformat()

    with open(config_yaml_path(), "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def start_new_session(
    thread_id: str | None = None,
    *,
    run_metadata: dict[str, Any] | None = None,
    model_binding: dict[str, Any] | None = None,
    update_config_current_session: bool = True,
) -> dict[str, Any]:
    """Create or update the session JSON and optionally record ``last_run`` audit metadata.

    If the session file already exists, ``messages``, ``turns``, and other fields are
    preserved; ``last_active`` and ``last_run`` are updated.

    ``model_binding`` (if provided) is the per-thread LLM routing snapshot: ``effective_model``,
    ``provider``, ``base_url``, ``merge_yaml_provider``, and merged ``llm`` kwargs. The CLI updates
    it on every run so resuming a session reuses the same model unless you pass ``-m`` / ``--provider``
    / ``--base-url`` / ``--llm-*`` overrides.

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
        if model_binding is not None:
            session_data["model_binding"] = model_binding
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
        if model_binding is not None:
            session_data["model_binding"] = model_binding

    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2)

    _ensure_session_yaml_sidecar(thread_id, model_binding=model_binding)

    if update_config_current_session:
        config = create_default_config()
        config.setdefault("session", {})["current_session"] = thread_id
        config.setdefault("session", {})["last_updated"] = datetime.now(UTC).isoformat()

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
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
    session["last_active"] = datetime.now(UTC).isoformat()
    session["turns"] = session.get("turns", 0) + 1

    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session, f, indent=2)

    mb = session.get("model_binding")
    _ensure_session_yaml_sidecar(thread_id, model_binding=mb if isinstance(mb, dict) else None)


def resolve_model(
    model_id: str | None,
    *,
    config: dict[str, Any] | None = None,
    interactive_providers: bool | None = None,
    provider: str | None = None,
    base_url: str | None = None,
    merge_yaml_provider: bool = True,
    llm_param_overrides: dict[str, Any] | None = None,
    llm_frozen: dict[str, Any] | None = None,
) -> Any:
    """Resolve model from ID or env var.

    CLI auto-wiring covers a subset (see ``model_resolver``). Optional extras for LangChain’s
    first-party packages live in ``pyproject.toml`` under ``[project.optional-dependencies]``.
    Integrations without their own ``langchain-*`` wheel typically need ``agloom[community]``.
    Doc index: https://docs.langchain.com/oss/python/integrations/chat

    When *config* is omitted, :func:`load_config` is used so project ``.agloom.yaml`` layers apply.
    ``ai.api_keys`` is merged into the process environment when resolving the model (and the CLI
    applies it for the full run) so LangChain sees standard ``*_API_KEY`` variables during invoke.
    Each key listed under ``ai.api_keys`` **overwrites** that environment variable for the process.

    ``ai.llm`` supplies decoding options (``temperature``, ``top_p``, ``max_tokens``, …). Built-in
    defaults come from :data:`_LLM_YAML_DEFAULTS` / :func:`baseline_llm_params`, then YAML overrides,
    then *llm_param_overrides* (e.g. CLI).
    *llm_frozen* replaces the ``ai.llm`` base (used when resuming a session that stored merged
    kwargs in ``sessions/<id>.json`` → ``model_binding.llm``); overrides still apply on top.

    Priority:
    1. Explicit model_id (non-``auto``) — strict; fails if the matching extra is missing.
       Uses ``provider`` / ``base_url`` kwargs when passed. Config ``ai.base_url`` still merges when
       the kwarg is omitted (Ollama / vLLM / compatible APIs); ``ai.provider`` merges only when
       *merge_yaml_provider* is True (see :func:`merged_provider_base_for_resolve`).
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

    merged_conf = load_config(None) if config is None else config
    ai_cfg = merged_conf.get("ai", {}) if isinstance(merged_conf.get("ai"), dict) else {}

    merge_ai_api_keys_into_process_env(ai_cfg)

    merged_provider, merged_base = merged_provider_base_for_resolve(
        ai_cfg,
        provider=provider,
        base_url=base_url,
        merge_yaml_provider=merge_yaml_provider,
    )

    merged_llm = merged_llm_params_for_resolve(
        ai_cfg,
        llm_frozen=llm_frozen,
        llm_param_overrides=llm_param_overrides,
    )

    # 1. Explicit override — must match installed integration.
    if model_id is not None and not _is_auto(model_id):
        return get_model(model_id.strip(), provider=merged_provider, base_url=merged_base, **merged_llm)

    cm_raw = ai_cfg.get("model")
    # 2. Config file — optional fallback when e.g. ``model: gpt-4o`` but only Groq extra is installed.
    if not _is_auto(cm_raw):
        cm_str = cm_raw.strip() if isinstance(cm_raw, str) else str(cm_raw).strip()
        try:
            return get_model(cm_str, provider=merged_provider, base_url=merged_base, **merged_llm)
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
            return get_model(str(mid).strip(), provider=merged_provider, base_url=merged_base, **merged_llm)
        except MissingProviderDependency:
            continue

    # 4. Infer from API keys.
    return try_resolve_llm_from_api_keys(interactive=interactive_providers, **merged_llm)


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
