"""Map ``agloom.runtime serve`` CLI arguments to :func:`agloom.create_agent` kwargs."""

from __future__ import annotations

import asyncio
import copy
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
from agloom.llm.sampling_presets import build_sampling_section_for_session_marker
from agloom.mcp_support import MCPServerConfig
from agloom.memory.session import SessionMemory
from agloom.models import PatternType

PATTERN_ALIASES: dict[str, PatternType] = {
    "react": PatternType.REACT,
    "sequential": PatternType.PLANNER_EXECUTOR,
    "pipeline": PatternType.PIPELINE,
    "blackboard": PatternType.BLACKBOARD,
    "reflection": PatternType.REFLECTION,
    "hitl": PatternType.REACT,
    "supervisor": PatternType.SUPERVISOR,
    "swarm": PatternType.SWARM,
    "direct": PatternType.DIRECT,
}


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
    if (pat := pick("pattern")) is not None:
        out.pattern = pat
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
    sk = pick("skip_tool_approval")
    if sk is not None and sk.lower() in ("1", "true", "yes"):
        out.require_tool_approval = False
    return out


def parse_pattern_name(raw: str | None) -> PatternType | None:
    if not raw or not raw.strip():
        return None
    key = raw.strip().lower()
    if key in PATTERN_ALIASES:
        return PATTERN_ALIASES[key]
    try:
        return PatternType[key.upper()]
    except KeyError as e:
        choices = ", ".join(sorted(PATTERN_ALIASES))
        raise ValueError(f"unknown pattern {raw!r}; try one of: {choices}") from e


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
    if model_id:
        return get_model(model_id, provider=provider, **kw)
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


def mcp_configs_from_args(args: Namespace) -> list[MCPServerConfig]:
    specs = getattr(args, "mcp", None) or []
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
    if getattr(args, "no_memory", False):
        from langgraph.store.memory import InMemoryStore

        out["memory"] = SessionMemory(store=InMemoryStore(), max_turns=1, auto_summarize=False)
        return out
    if not mt or mt in ("default", "auto"):
        return out
    if mt == "none":
        from langgraph.store.memory import InMemoryStore

        out["memory"] = SessionMemory(store=InMemoryStore(), max_turns=1, auto_summarize=False)
        return out
    if mt == "in-memory":
        from langgraph.store.memory import InMemoryStore

        out["memory"] = SessionMemory(store=InMemoryStore())
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
    sm = SessionMemory(store=store)

    async def cleanup() -> None:
        await stack.aclose()

    return sm, cleanup


DEFAULT_SESSION_MAX_TURNS = 50
"""Aligned with starter ``agloom.yaml`` ``memory.max_turns`` and CLI defaults."""


def session_started_snapshot_from_args(args: Namespace) -> dict[str, Any]:
    """Serializable effective-config snapshot for ``.agloom/sessions/<id>.json`` (no secrets).

    Records how the LLM was resolved (explicit ``--model`` vs env auto-detect), optional
    ``--api-key-env`` name and whether that variable was non-empty at process start, plus
    memory / summarization flags so edited YAML on the next launch diffs clearly from older
    session markers.
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
    eff: dict[str, Any] = {
        "model": model_out,
        "provider": getattr(args, "provider", None),
        "llm_resolution": "explicit_model" if model_out else "env_auto",
        "api_key_env": str(api_env) if api_env else None,
        "api_key_env_nonempty": api_present,
        "session_max_turns": sm_turns,
        "auto_summarize": bool(getattr(args, "auto_summarize", True)),
        "summarizer_model": getattr(args, "summarizer_model", None),
        "memory_type": getattr(args, "memory_type", None),
        "memory_path": getattr(args, "memory_path", None),
        "no_memory": bool(getattr(args, "no_memory", False)),
    }
    tx = getattr(args, "temperature", None)
    if tx is not None:
        eff["temperature"] = float(tx)
    tpp = getattr(args, "top_p", None)
    if tpp is not None:
        eff["top_p"] = float(tpp)
    tk = getattr(args, "top_k", None)
    if tk is not None:
        eff["top_k"] = int(tk)
    eff["with_cli_tools"] = bool(getattr(args, "with_cli_tools", False))
    eff["require_tool_approval"] = bool(getattr(args, "require_tool_approval", True))

    return {
        "effective_config": eff,
        "sampling": build_sampling_section_for_session_marker(args),
    }


def build_create_agent_kwargs(args: Namespace) -> dict[str, Any]:
    """Non-model kwargs for :func:`agloom.create_agent` (merge after ``model=``)."""
    mk = memory_kwargs_from_args(args)
    fp = parse_pattern_name(getattr(args, "pattern", None))
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
    if fp is not None:
        kwargs["fallback_pattern"] = fp
    if getattr(args, "auto_summarize", True) is False:
        kwargs["auto_summarize"] = False

    if getattr(args, "no_skills", False):
        kwargs["skills_disk_mirror"] = None
    elif skills is not None:
        kwargs["skills_disk_mirror"] = skills

    kwargs["require_tool_approval_for_cli_tools"] = bool(getattr(args, "require_tool_approval", True))

    return kwargs


def skills_disk_mirror_from_args(args: Namespace) -> Path | None:
    if getattr(args, "no_skills", False):
        return None
    sd = getattr(args, "skills_dir", None)
    if sd:
        return Path(str(sd)).expanduser().resolve()
    return None
