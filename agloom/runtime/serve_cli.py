"""Map ``agloom.runtime serve`` CLI arguments to :func:`agloom.create_agent` kwargs."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
from argparse import Namespace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from agloom.llm import get_model, try_resolve_llm_from_api_keys
from agloom.llm.llm_provider_params import normalize_provider_slug
from agloom.llm.model_resolver import split_provider_prefix
from agloom.llm.provider_registry import PROVIDER_ENV_KEYS
from agloom.llm.sampling_presets import build_sampling_section_for_session_marker, infer_provider_slug_from_args
from agloom.mcp_support import MCPServerConfig
from agloom.memory.session import SessionMemory


def cli_tools_options_from_args(args: Namespace) -> dict[str, Any] | None:
    """Builtin CLI tools bundle for :func:`agloom.create_agent` ``cli_tools=``."""
    if not getattr(args, "with_cli_tools", False):
        return None
    return {
        "working_dir": getattr(args, "cli_tools_working_dir", ".") or ".",
        "allow_shell": not getattr(args, "cli_tools_no_shell", False),
        "allow_network": not getattr(args, "cli_tools_no_network", False),
        "sandbox": not getattr(args, "cli_tools_no_sandbox", False),
    }


def merge_ws_connection_args(base: Namespace, request_path: str) -> Namespace:
    """Merge ``?model=&provider=&temperature=…`` query overrides into a copy of *base*.

    Intended for WebSocket handshake paths — **do not** pass API keys in the query string.
    """
    out = copy.copy(base)
    if not request_path or "?" not in request_path:
        return out
    qs = parse_qs(urlparse(request_path).query)

    def pick(key: str) -> str | None:
        v = qs.get(key)
        if not v or not v[0]:
            return None
        s = v[0].strip()
        return s if s else None

    if (m := pick("model")) is not None:
        out.model = m
    if (p := pick("provider")) is not None:
        out.provider = p
    if (t := pick("temperature")) is not None:
        try:
            out.temperature = float(t)
        except ValueError:
            pass
    if (tp := pick("top_p")) is not None:
        try:
            out.top_p = float(tp)
        except ValueError:
            pass
    if (tk := pick("top_k")) is not None:
        try:
            out.top_k = int(tk)
        except ValueError:
            pass
    if (sm := pick("session_max_turns")) is not None:
        try:
            out.session_max_turns = int(sm)
        except ValueError:
            pass
    if (mt := pick("max_tokens")) is not None:
        try:
            out.max_tokens = int(mt)
        except ValueError:
            pass
    if (fp := pick("frequency_penalty")) is not None:
        try:
            out.frequency_penalty = float(fp)
        except ValueError:
            pass
    if (pp := pick("presence_penalty")) is not None:
        try:
            out.presence_penalty = float(pp)
        except ValueError:
            pass
    sk = pick("skip_tool_approval")
    if sk is not None and sk.lower() in ("1", "true", "yes"):
        out.require_tool_approval = False
    return out


def apply_api_key_env(args: Namespace) -> None:
    var = getattr(args, "api_key_env", None)
    if not var:
        return
    secret = os.environ.get(str(var))
    if not secret or not secret.strip():
        raise RuntimeError(f"--api-key-env {var!r}: environment variable is unset or empty")
    prov = getattr(args, "provider", None)
    mid = getattr(args, "model", None)
    slug: str | None = None
    if prov:
        slug = normalize_provider_slug(str(prov).strip())
    elif mid:
        pref, _rest = split_provider_prefix(str(mid).strip())
        if pref:
            slug = normalize_provider_slug(pref)
    if not slug:
        raise RuntimeError(
            "--api-key-env requires --provider or a model id with a provider prefix (e.g. openai:gpt-4o)"
        )
    keys = PROVIDER_ENV_KEYS.get(slug)
    if not keys:
        raise RuntimeError(f"No API key env mapping for provider {slug!r}")
    os.environ[keys[0]] = secret.strip()


def _persist_api_key_marker_requested(args: Namespace) -> bool:
    if getattr(args, "persist_api_key_in_session_marker", False):
        return True
    v = (os.environ.get("AGLOOM_PERSIST_API_KEY_IN_SESSION_MARKER") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def inject_api_key_secret_from_session_marker(args: Namespace, marker_path: Path | None) -> None:
    """If the session marker contains ``effective_config.api_key_secret``, copy it into the env var.

    Only runs when the target variable named in the marker is **unset or empty** so a live
    process environment always wins over stale JSON.

    Pairs with :func:`session_started_snapshot_from_args` when the marker contains
    ``api_key_secret`` (default unless ``AGLOOM_OMIT_API_KEY_FROM_SESSION=1``). The
    ``--persist-api-key-in-session-marker`` flag only adds
    ``persist_api_key_in_session_marker: true`` to the snapshot for audit.
    """
    if marker_path is None or not marker_path.is_file():
        return
    try:
        raw = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return
    if not isinstance(raw, dict):
        return
    eff = raw.get("effective_config")
    if not isinstance(eff, dict):
        return
    secret = eff.get("api_key_secret")
    if not isinstance(secret, str) or not secret.strip():
        return
    target: str | None = None
    for key in ("api_key_env", "credential_env_var", "provider_primary_api_key_env"):
        v = eff.get(key)
        if isinstance(v, str) and v.strip():
            target = v.strip()
            break
    if not target:
        return
    if (os.environ.get(target) or "").strip():
        return
    os.environ[target] = secret.strip()


def merge_api_key_env_from_session_marker(args: Namespace, marker_path: Path | None) -> None:
    """When ``--api-key-env`` was not passed, copy ``effective_config.api_key_env`` from the marker.

    Session JSON records the credential source as ``api_key_env`` (and may omit duplicate
    ``credential_env_var`` / ``provider_primary_api_key_env`` when they match). Users can edit
    ``api_key_env`` and restart the same session id to switch sources. Falls back to legacy
    ``credential_env_var`` / ``provider_primary_api_key_env`` on older markers.
    :func:`apply_api_key_env` then maps that var's value into the provider's canonical key.

    CLI ``--api-key-env`` always wins over the marker.
    """
    if getattr(args, "api_key_env", None):
        return
    if marker_path is None or not marker_path.is_file():
        return
    try:
        raw = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return
    if not isinstance(raw, dict):
        return
    eff = raw.get("effective_config")
    if not isinstance(eff, dict):
        return
    for key in ("api_key_env", "credential_env_var", "provider_primary_api_key_env"):
        v = eff.get(key)
        if isinstance(v, str) and v.strip():
            args.api_key_env = v.strip()
            return


def resolve_llm_for_serve(args: Namespace) -> Any | None:
    model_id = getattr(args, "model", None)
    provider = getattr(args, "provider", None)
    kw: dict[str, Any] = {}
    t = getattr(args, "temperature", None)
    if t is not None:
        kw["temperature"] = float(t)
    tp = getattr(args, "top_p", None)
    if tp is not None:
        kw["top_p"] = float(tp)
    tk = getattr(args, "top_k", None)
    if tk is not None:
        kw["top_k"] = int(tk)
    mt = getattr(args, "max_tokens", None)
    if mt is not None:
        kw["max_tokens"] = int(mt)
    fpen = getattr(args, "frequency_penalty", None)
    if fpen is not None:
        kw["frequency_penalty"] = float(fpen)
    ppen = getattr(args, "presence_penalty", None)
    if ppen is not None:
        kw["presence_penalty"] = float(ppen)
    bu = getattr(args, "base_url", None)
    if isinstance(bu, str) and bu.strip():
        kw["base_url"] = bu.strip()
    mid = (str(model_id).strip() if model_id is not None else "")
    if mid and mid.lower() != "auto":
        return get_model(mid, provider=provider, **kw)
    return try_resolve_llm_from_api_keys(interactive=False, **kw)


def system_prompt_from_args(args: Namespace) -> Any | None:
    fp = getattr(args, "system_prompt_file", None)
    if fp:
        p = Path(str(fp)).expanduser()
        return p.read_text(encoding="utf-8")
    sp = getattr(args, "system_prompt", None)
    if sp:
        return str(sp)
    return None


def _resolve_mcp_spec(spec: str, yaml_dir: Path) -> str:
    """Resolve ``name:relative.yaml`` against the directory that contains ``agloom.yaml``."""
    spec = spec.strip()
    if ":" not in spec:
        return spec
    name, _, path_part = spec.partition(":")
    name = name.strip()
    path_part = path_part.strip()
    if not path_part:
        raise ValueError(f"invalid MCP entry {spec!r}; expected name:path")
    p = Path(path_part)
    resolved = p.resolve() if p.is_absolute() else (yaml_dir / p).resolve()
    return f"{name}:{resolved}"


def mcp_specs_from_agloom_yaml(cwd: Path | None = None) -> list[str]:
    """Expand ``mcp`` / ``mcp.servers`` from ``.agloom/agloom.yaml`` (or root ``agloom.yaml``).

    Used when ``agloom-runtime`` is started without ``--mcp`` fragments (e.g. plain
    ``python -m agloom.runtime``) so MCP still matches the nested project YAML.
    """
    import yaml

    root = cwd or Path.cwd()
    for yaml_path in (root / ".agloom" / "agloom.yaml", root / "agloom.yaml"):
        if not yaml_path.is_file():
            continue
        try:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(raw, dict):
            continue
        mcp_raw = raw.get("mcp")
        entries: list[Any] = []
        if isinstance(mcp_raw, dict):
            servers = mcp_raw.get("servers")
            if isinstance(servers, list):
                entries = servers
        elif isinstance(mcp_raw, list):
            entries = mcp_raw
        if not entries:
            continue
        yaml_dir = yaml_path.parent
        out: list[str] = []
        for entry in entries:
            if isinstance(entry, str):
                out.append(_resolve_mcp_spec(entry, yaml_dir))
            elif isinstance(entry, dict):
                name = str(entry.get("name") or "").strip()
                cfg = entry.get("config")
                if not name or not isinstance(cfg, str) or not cfg.strip():
                    continue
                p = Path(cfg.strip())
                resolved = p.resolve() if p.is_absolute() else (yaml_dir / p).resolve()
                out.append(f"{name}:{resolved}")
        if out:
            return out
    return []


def mcp_configs_from_args(args: Namespace, *, cwd: Path | None = None) -> list[MCPServerConfig]:
    specs = list(getattr(args, "mcp", None) or [])
    if not specs:
        specs = mcp_specs_from_agloom_yaml(cwd)
    if not specs:
        return []
    import yaml

    out: list[MCPServerConfig] = []
    for spec in specs:
        if ":" not in spec:
            raise ValueError(f"invalid --mcp {spec!r}; expected name:path/to.yaml")
        name, _, path = spec.partition(":")
        name = name.strip()
        path_p = Path(path.strip()).expanduser().resolve()
        raw = yaml.safe_load(path_p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"MCP yaml {path_p} must be a mapping")
        merged = dict(raw)
        merged.setdefault("name", name)
        out.append(MCPServerConfig.model_validate(merged))
    return out


def mcp_server_names_configured_from_args(args: Namespace) -> list[str]:
    """MCP server names from argv/YAML (for ``runtime.ready`` before lazy connect)."""
    try:
        cfgs = mcp_configs_from_args(args)
    except Exception:
        return []
    names: list[str] = []
    for c in cfgs:
        n = str(getattr(c, "name", "") or "").strip()
        if n:
            names.append(n)
    return names


def cli_tools_bundle_metrics_from_args(args: Namespace) -> tuple[bool, int]:
    """Bundled CLI tool count matching ``create_agent`` (includes ``task`` tool slot)."""
    opts = cli_tools_options_from_args(args)
    if opts is None:
        return False, 0
    from agloom.cli_tools import get_cli_tools

    cell: list[Any | None] = [None]
    tools = get_cli_tools(
        working_dir=opts.get("working_dir", ".") or ".",
        allow_shell=bool(opts.get("allow_shell", True)),
        allow_network=bool(opts.get("allow_network", True)),
        sandbox=bool(opts.get("sandbox", True)),
        task_agent_cell=cell,
    )
    return True, len(tools)


def session_memory_mode_sidebar_from_args(args: Namespace) -> str:
    """Short label for UIs: rolling session memory from CLI before agent bootstrap.

    When ``--memory`` is omitted, :func:`agloom.unified_agent.create_agent` still attaches
    ephemeral :class:`~agloom.memory.session.SessionMemory` (LangGraph in-memory store), so the
    sidebar reports ``in-memory`` rather than ``off``.
    """
    mt = (getattr(args, "memory_type", None) or "").strip().lower()
    if not mt or mt in ("default", "auto"):
        return "in-memory"
    if mt == "sqlite":
        return "sqlite"
    if mt == "in-memory":
        return "in-memory"
    if mt == "none":
        return "none"
    return mt


def agent_store_kind_sidebar_from_args(args: Namespace) -> str:
    """LangGraph LT store slug (skills / harness stack when not ``none``)."""
    raw = getattr(args, "agent_store", None)
    if raw is None:
        return "sqlite"
    s = str(raw).strip()
    return s.lower() if s else "sqlite"


def runtime_ready_sidebar_from_args(args: Namespace) -> dict[str, Any]:
    """Kwargs fragment for :meth:`SessionEmitter.emit_runtime_ready` (stdio pre-bootstrap)."""
    cli_en, cli_ct = cli_tools_bundle_metrics_from_args(args)
    return {
        "cli_tools_enabled": cli_en,
        "cli_tools_count": cli_ct,
        "session_memory_mode": session_memory_mode_sidebar_from_args(args),
        "agent_store_kind": agent_store_kind_sidebar_from_args(args),
        "mcp_servers_configured": mcp_server_names_configured_from_args(args),
    }


def summarizer_model_from_args(args: Namespace) -> Any | None:
    sm = getattr(args, "summarizer_model", None)
    if not sm:
        return None
    return get_model(sm)


def memory_kwargs_from_args(args: Namespace) -> dict[str, Any]:
    """Session-memory kwargs for ``create_agent`` (excluding sqlite — handled in ``__main__``)."""
    out: dict[str, Any] = {}
    mt = (getattr(args, "memory_type", None) or "").strip().lower()
    if mt == "sqlite":
        return out
    if not mt or mt in ("default", "auto"):
        return out
    if mt == "none":
        from langgraph.store.memory import InMemoryStore

        out["memory"] = SessionMemory(store=InMemoryStore(), max_turns=1, auto_summarize=False)
        return out
    if mt == "in-memory":
        from langgraph.store.memory import InMemoryStore

        _budget: int | None = None
        raw_mt = getattr(args, "max_tokens", None)
        if raw_mt is not None:
            try:
                n = int(raw_mt)
                if n > 0:
                    _budget = n
            except (TypeError, ValueError):
                pass
        out["memory"] = SessionMemory(store=InMemoryStore(), summarize_max_tokens_budget=_budget)
        return out
    raise ValueError(f"unsupported --memory {mt!r} (try in-memory, none, sqlite)")


async def open_sqlite_session_memory(
    args: Namespace,
    *,
    ws_session_id: str | None = None,
) -> tuple[Any, Any]:
    """If ``--memory sqlite``, return ``(SessionMemory, cleanup_coro)`` else ``(None, None)``.

    With *ws_session_id*, isolate DB files per WebSocket session so concurrent connections do not
    share the same SQLite store file.
    """
    mt = (getattr(args, "memory_type", None) or "").strip().lower()
    if mt != "sqlite":
        return None, None
    raw = getattr(args, "memory_path", None) or ".agloom/session_memory.sqlite"

    def _prepare_sqlite_path() -> Path:
        base = Path(str(raw)).expanduser()
        if not base.is_absolute():
            p = (Path.cwd() / base).resolve()
        else:
            p = base.resolve()
        if ws_session_id:
            safe = re.sub(r"[^\w.\-+=]", "_", ws_session_id.strip()) or "session"
            p = p.parent / f"{p.stem}_{safe}{p.suffix}"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    db_path = await asyncio.to_thread(_prepare_sqlite_path)
    conn = str(db_path)
    from contextlib import AsyncExitStack

    from langgraph.store.sqlite import AsyncSqliteStore

    stack = AsyncExitStack()
    store = await stack.enter_async_context(AsyncSqliteStore.from_conn_string(conn))
    await store.setup()
    mt = getattr(args, "max_tokens", None)
    mt_budget: int | None = None
    if mt is not None:
        try:
            n = int(mt)
            if n > 0:
                mt_budget = n
        except (TypeError, ValueError):
            pass
    sm = SessionMemory(
        store=store,
        max_turns=int(getattr(args, "session_max_turns", 50) or 50),
        auto_summarize=bool(getattr(args, "auto_summarize", True)),
        summarize_max_tokens_budget=mt_budget,
    )

    async def cleanup() -> None:
        await stack.aclose()

    return sm, cleanup


DEFAULT_SESSION_MAX_TURNS = 50
"""Aligned with starter ``agloom.yaml`` ``memory.max_turns`` and CLI defaults."""

# Always written under ``effective_config`` in ``.agloom/sessions/<id>.json`` (user-editable).
SESSION_MARKER_DEFAULT_MAX_TOKENS = 8192
SESSION_MARKER_DEFAULT_FREQUENCY_PENALTY = 0.0
SESSION_MARKER_DEFAULT_PRESENCE_PENALTY = 0.0


def _provider_credential_env_status(resolved_slug: str | None) -> list[dict[str, Any]]:
    """Per-env presence for the resolved provider (no values)."""
    if not resolved_slug:
        return []
    keys = PROVIDER_ENV_KEYS.get(resolved_slug)
    if not keys:
        return []
    return [{"env": name, "present": bool((os.environ.get(name) or "").strip())} for name in keys]


def _any_curated_provider_api_key_present() -> bool:
    """True when any registry-listed API key env is non-empty (used when ``provider_resolved`` is unknown)."""
    from agloom.llm.provider_registry import PROVIDERS

    for p in PROVIDERS.values():
        for k in p.resolver_env_keys:
            if (os.environ.get(k) or "").strip():
                return True
    return False


def _provider_primary_api_key_env_name(resolved_slug: str | None) -> str | None:
    """First canonical provider env var that is non-empty (name only; never the secret value)."""
    from agloom.llm.provider_registry import PROVIDERS

    if resolved_slug and isinstance(resolved_slug, str):
        slug = resolved_slug.strip().lower()
        p = PROVIDERS.get(slug)
        if p:
            for k in p.resolver_env_keys:
                if (os.environ.get(k) or "").strip():
                    return k
            return None
    for p in PROVIDERS.values():
        for k in p.resolver_env_keys:
            if (os.environ.get(k) or "").strip():
                return k
    return None


def _llm_endpoint_snapshot(args: Namespace) -> dict[str, Any]:
    """Non-secret HTTP hints matching :mod:`agloom.llm.model_resolver` env conventions."""
    out: dict[str, Any] = {}
    bu = getattr(args, "base_url", None)
    if isinstance(bu, str) and bu.strip():
        out["base_url"] = bu.strip()
    oll = os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST")
    if oll:
        oll_s = oll.strip()
        if oll_s:
            out["ollama_base_url_from_env"] = oll_s
    compat = os.environ.get("VLLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    if compat:
        compat_s = compat.strip()
        if compat_s:
            out["openai_compatible_base_url_from_env"] = compat_s
    return out


def _omit_api_key_secret_from_session_marker() -> bool:
    v = (os.environ.get("AGLOOM_OMIT_API_KEY_FROM_SESSION") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def session_started_snapshot_from_args(args: Namespace) -> dict[str, Any]:
    """Serializable effective-config snapshot for ``.agloom/sessions/<id>.json``.

    By default ``effective_config`` includes ``api_key_secret`` (key material copied from the
    resolved credential env var) so you can edit the session file and resume without the shell
    env. **Treat session JSON as secret-bearing** — do not commit ``.agloom/sessions/`` to git.
    Set ``AGLOOM_OMIT_API_KEY_FROM_SESSION=1`` to skip writing ``api_key_secret`` (names-only
    snapshot).

    With ``--persist-api-key-in-session-marker`` or ``AGLOOM_PERSIST_API_KEY_IN_SESSION_MARKER=1``,
    ``persist_api_key_in_session_marker: true`` is also set on the snapshot for explicit audit.

    Resume uses :func:`inject_api_key_secret_from_session_marker` when the named env var is
    empty and the marker still carries ``api_key_secret``.

    ``effective_config`` always includes ``max_tokens``, ``frequency_penalty``, and
    ``presence_penalty`` (defaults when omitted on the CLI); users may override via flags or
    by editing the session JSON.

    ``provider`` is the explicit ``--provider`` CLI value only (often ``None``). Use
    ``provider_resolved`` for the slug inferred from ``--provider`` or ``provider:`` model
    prefix. ``provider_credential_env`` lists canonical env vars for that slug and whether
    each was non-empty (names only in that list).

    ``api_key_env`` / ``api_key_env_nonempty`` identify the env var whose value is stored in
    ``api_key_secret`` (``--api-key-env`` remap, else first non-empty canonical key for the
    provider). ``credential_env_var`` / ``provider_primary_api_key_env`` are only written when
    they differ from ``api_key_env`` (remap / older layouts).

    ``provider_primary_credential_present`` is ``True`` when any canonical var for the resolved
    slug was set, or when ``provider_resolved`` is ``None`` and any curated provider API key env
    was set.
    """
    api_env = getattr(args, "api_key_env", None)
    api_present = False
    if api_env:
        secret = os.environ.get(str(api_env))
        api_present = bool(secret and secret.strip())
    sm_turns = int(getattr(args, "session_max_turns", DEFAULT_SESSION_MAX_TURNS) or DEFAULT_SESSION_MAX_TURNS)
    raw_model = getattr(args, "model", None)
    model_out: str | None = None
    if isinstance(raw_model, str):
        stripped = raw_model.strip()
        model_out = stripped if stripped else None
    elif raw_model:
        model_out = str(raw_model).strip() or None
    resolved_slug = infer_provider_slug_from_args(args)
    cred_status = _provider_credential_env_status(resolved_slug)
    if resolved_slug:
        any_primary_cred = bool(cred_status) and any(bool(x.get("present")) for x in cred_status)
    else:
        any_primary_cred = _any_curated_provider_api_key_present()
    primary = _provider_primary_api_key_env_name(resolved_slug)
    cred_var: str | None = None
    cred_nonempty = False
    if api_env:
        cred_var = str(api_env).strip() or None
        cred_nonempty = api_present
    elif primary and (os.environ.get(primary) or "").strip():
        cred_var = primary
        cred_nonempty = True
    api_env_s = str(api_env).strip() if api_env else ""
    snapshot_api_key_env = api_env_s if api_env_s else cred_var
    snapshot_api_key_nonempty = api_present if api_env_s else cred_nonempty
    eff: dict[str, Any] = {
        "model": model_out,
        "provider": getattr(args, "provider", None),
        "provider_resolved": resolved_slug,
        "llm_resolution": "explicit_model" if model_out else "env_auto",
        "api_key_env": snapshot_api_key_env,
        "api_key_env_nonempty": snapshot_api_key_nonempty,
        "provider_primary_credential_present": any_primary_cred,
        "provider_credential_env": cred_status,
        "session_max_turns": sm_turns,
        "auto_summarize": bool(getattr(args, "auto_summarize", True)),
        "summarizer_model": getattr(args, "summarizer_model", None),
        "memory_type": getattr(args, "memory_type", None),
        "memory_path": getattr(args, "memory_path", None),
    }
    if cred_var != snapshot_api_key_env or cred_nonempty != snapshot_api_key_nonempty:
        eff["credential_env_var"] = cred_var
        eff["credential_env_var_nonempty"] = cred_nonempty
    if primary and primary != snapshot_api_key_env:
        eff["provider_primary_api_key_env"] = primary
    endpoint = _llm_endpoint_snapshot(args)
    if endpoint:
        eff["llm_endpoint"] = endpoint
    tx = getattr(args, "temperature", None)
    if tx is not None:
        eff["temperature"] = float(tx)
    tpp = getattr(args, "top_p", None)
    if tpp is not None:
        eff["top_p"] = float(tpp)
    tk = getattr(args, "top_k", None)
    if tk is not None:
        eff["top_k"] = int(tk)
    mt = getattr(args, "max_tokens", None)
    eff["max_tokens"] = int(mt) if mt is not None else SESSION_MARKER_DEFAULT_MAX_TOKENS
    fp = getattr(args, "frequency_penalty", None)
    eff["frequency_penalty"] = (
        float(fp) if fp is not None else SESSION_MARKER_DEFAULT_FREQUENCY_PENALTY
    )
    pp = getattr(args, "presence_penalty", None)
    eff["presence_penalty"] = (
        float(pp) if pp is not None else SESSION_MARKER_DEFAULT_PRESENCE_PENALTY
    )
    eff["with_cli_tools"] = bool(getattr(args, "with_cli_tools", False))
    eff["require_tool_approval"] = bool(getattr(args, "require_tool_approval", True))

    if not _omit_api_key_secret_from_session_marker() and cred_var and cred_nonempty:
        mat = os.environ.get(cred_var)
        if isinstance(mat, str) and mat.strip():
            eff["api_key_secret"] = mat.strip()
    if _persist_api_key_marker_requested(args):
        eff["persist_api_key_in_session_marker"] = True

    return {
        "effective_config": eff,
        "sampling": build_sampling_section_for_session_marker(args),
    }


def build_create_agent_kwargs(args: Namespace) -> dict[str, Any]:
    """Non-model kwargs for :func:`agloom.create_agent` (merge after ``model=``)."""
    mk = memory_kwargs_from_args(args)
    mc = mcp_configs_from_args(args)
    sm = summarizer_model_from_args(args)
    sp = system_prompt_from_args(args)
    skills = skills_disk_mirror_from_args(args)

    sm_turns = int(getattr(args, "session_max_turns", DEFAULT_SESSION_MAX_TURNS) or DEFAULT_SESSION_MAX_TURNS)

    kwargs: dict[str, Any] = {
        "session_max_turns": sm_turns,
        **mk,
    }
    if mc:
        kwargs["mcp_servers"] = mc
    if sm is not None:
        kwargs["summarizer_model"] = sm
    if sp is not None:
        kwargs["system_prompt"] = sp
    if getattr(args, "auto_summarize", True) is False:
        kwargs["auto_summarize"] = False

    kwargs["skills_disk_mirror"] = skills

    kwargs["require_tool_approval_for_cli_tools"] = bool(getattr(args, "require_tool_approval", True))

    return kwargs


def skills_disk_mirror_from_args(args: Namespace, *, cwd: Path | None = None) -> Path:
    """Default ``.agloom/skills`` under *cwd* (usually process cwd) so learned skills mirror to disk."""
    sd = getattr(args, "skills_dir", None)
    if sd:
        return Path(str(sd)).expanduser().resolve()
    base = cwd if cwd is not None else Path.cwd()
    return (base / ".agloom" / "skills").resolve()
