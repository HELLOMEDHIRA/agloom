"""Map ``agloom.runtime serve`` CLI arguments to :func:`agloom.create_agent` kwargs."""

from __future__ import annotations

import asyncio
import os
from argparse import Namespace
from pathlib import Path
from typing import Any

from agloom.llm import get_model, try_resolve_llm_from_api_keys
from agloom.llm.llm_provider_params import normalize_provider_slug
from agloom.llm.model_resolver import split_provider_prefix
from agloom.llm.provider_registry import PROVIDER_ENV_KEYS
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


async def open_sqlite_session_memory(args: Namespace) -> tuple[Any, Any]:
    """If ``--memory sqlite``, return ``(SessionMemory, cleanup_coro)`` else ``(None, None)``."""
    mt = (getattr(args, "memory_type", None) or "").strip().lower()
    if mt != "sqlite":
        return None, None
    raw = getattr(args, "memory_path", None) or ".agloom/session_memory.sqlite"

    def _prepare_sqlite_path() -> Path:
        p = Path(str(raw)).expanduser().resolve()
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


def build_create_agent_kwargs(args: Namespace) -> dict[str, Any]:
    """Non-model kwargs for :func:`agloom.create_agent` (merge after ``model=``)."""
    mk = memory_kwargs_from_args(args)
    fp = parse_pattern_name(getattr(args, "pattern", None))
    mc = mcp_configs_from_args(args)
    sm = summarizer_model_from_args(args)
    sp = system_prompt_from_args(args)
    skills = skills_disk_mirror_from_args(args)

    sm_turns = int(getattr(args, "session_max_turns", 20) or 20)

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

    return kwargs


def skills_disk_mirror_from_args(args: Namespace) -> Path | None:
    if getattr(args, "no_skills", False):
        return None
    sd = getattr(args, "skills_dir", None)
    if sd:
        return Path(str(sd)).expanduser().resolve()
    return None
