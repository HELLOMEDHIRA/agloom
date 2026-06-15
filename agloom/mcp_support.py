"""MCP client wiring: ``MCPServerConfig``, connect helpers, capability merge for agents/workers.

Uses ``langchain-mcp-adapters``; ``connect_mcp_servers`` is invoked lazily from ``UnifiedAgent``.
"""

from __future__ import annotations

import inspect
import weakref
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, model_validator

from .logging_utils import get_logger

logger = get_logger(__name__)


def _adapter_transport(transport: str) -> str:
    """Map Agloom config aliases to langchain-mcp-adapters transport names."""
    if transport == "http":
        return "streamable_http"
    return transport


def _unwrap_exception(exc: BaseException) -> BaseException:
    """Return the deepest useful leaf from ExceptionGroup / cause chains."""
    current = exc
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        group_types: tuple[type, ...] = (ExceptionGroup, BaseExceptionGroup)
        if isinstance(current, group_types) and getattr(current, "exceptions", None):
            current = current.exceptions[0]
            continue
        cause = current.__cause__ or current.__context__
        if cause is not None and cause is not current:
            current = cause
            continue
        break
    return current


def format_mcp_connect_error(
    cfg: MCPServerConfig,
    exc: BaseException,
    *,
    transport_used: str | None = None,
) -> str:
    """Single-line diagnostic: server, transport, url, optional HTTP status, root cause."""
    root = _unwrap_exception(exc)
    transport = transport_used or _adapter_transport(cfg.transport)
    parts = [f"server={cfg.name!r}", f"transport={transport}"]
    if cfg.url:
        parts.append(f"url={cfg.url}")
    for attr in ("status_code", "code", "errno"):
        code = getattr(root, attr, None)
        if isinstance(code, int):
            parts.append(f"status={code}")
            break
    msg = str(root).strip() or repr(root)
    parts.append(f"error={msg}")
    return "; ".join(parts)


class MCPConnectionError(Exception):
    """Raised when one or more configured MCP servers fail to connect (strict mode)."""


class MCPServerConfig(BaseModel):
    """
    One MCP server endpoint.

    Stdio (local process):
        MCPServerConfig(
            name="filesystem", transport="stdio",
            command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/data"]
        )

    SSE (remote HTTP):
        MCPServerConfig(
            name="weather", transport="sse",
            url="http://localhost:8000/mcp"
        )

    Streamable HTTP:
        MCPServerConfig(
            name="api", transport="streamable_http",
            url="https://api.example.com/mcp"
        )
    """

    name: str
    transport: Literal["stdio", "sse", "streamable_http", "http"]

    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None

    url: str | None = None
    headers: dict[str, str] | None = None

    timeout: float = 30.0

    @model_validator(mode="after")
    def _check(self) -> MCPServerConfig:
        if self.transport == "stdio" and not self.command:
            raise ValueError(f"[{self.name}] stdio transport requires 'command'")
        if self.transport in ("sse", "streamable_http", "http") and not self.url:
            raise ValueError(f"[{self.name}] {self.transport} transport requires 'url'")
        return self

    def to_client_dict(self, *, transport_override: str | None = None) -> dict[str, Any]:
        if self.transport == "stdio":
            d: dict[str, Any] = {
                "command": self.command,
                "args": self.args,
                "transport": "stdio",
            }
            if self.env:
                d["env"] = self.env
        else:
            transport = _adapter_transport(transport_override or self.transport)
            d = {"url": self.url, "transport": transport}
            if self.headers:
                d["headers"] = self.headers
        return d


def _build_server_dict(
    servers: list[MCPServerConfig],
    transport_overrides: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    overrides = transport_overrides or {}
    return {
        cfg.name: cfg.to_client_dict(transport_override=overrides.get(cfg.name))
        for cfg in servers
    }


@dataclass
class MCPCapabilities:
    """
    Everything loaded from one MCP server after connect.

    tools          → BaseTool list, ready to give to workers
    resource_tool  → BaseTool wrapping read_resource(uri) — optional, None if no resources
    prompt_tool    → BaseTool wrapping get_prompt(name, args) — optional, None if no prompts
    prompt_names   → list of available prompt names (for classifier awareness)
    resource_uris  → list of available resource URIs (for classifier awareness)
    last_error     → set when the primary tool load for this server fails (diagnostics / AGP)
    """

    server_name: str
    tools: list[BaseTool] = field(default_factory=list)
    resource_tool: BaseTool | None = None
    prompt_tool: BaseTool | None = None
    prompt_names: list[str] = field(default_factory=list)
    resource_uris: list[str] = field(default_factory=list)
    last_error: str | None = None
    transport_used: str | None = None

    def all_tools(self) -> list[BaseTool]:
        """All BaseTool objects from this server — tools + resource_tool + prompt_tool."""
        result = list(self.tools)
        if self.resource_tool:
            result.append(self.resource_tool)
        if self.prompt_tool:
            result.append(self.prompt_tool)
        return result


async def _populate_server_capabilities(
    client: Any,
    client_holder: dict[str, Any],
    cfg: MCPServerConfig,
    cap: MCPCapabilities,
) -> None:
    """Load tools, resources, and prompts for one MCP server (raises on tool load failure)."""
    cap.tools = await client.get_tools(server_name=cfg.name)

    try:
        async with client.session(cfg.name) as session:
            res_response = await session.list_resources()
            uris = [str(r.uri) for r in res_response.resources]
            cap.resource_uris = uris

        if uris:
            cap.resource_tool = _make_resource_tool(
                server_name=cfg.name,
                client_holder=client_holder,
                uris=uris,
            )
            logger.info(f"MCP [{cfg.name}]: {len(uris)} resource(s) → tool 'read_resource_{cfg.name}'")
    except Exception as e:
        logger.debug(f"MCP [{cfg.name}]: no resources or list_resources unsupported — {e}")

    try:
        async with client.session(cfg.name) as session:
            prompt_response = await session.list_prompts()
            names = [p.name for p in prompt_response.prompts]
            cap.prompt_names = names

        if names:
            cap.prompt_tool = _make_prompt_tool(
                server_name=cfg.name,
                client_holder=client_holder,
                prompt_names=names,
            )
            logger.info(f"MCP [{cfg.name}]: {len(names)} prompt(s) {names} → tool 'get_prompt_{cfg.name}'")
    except Exception as e:
        logger.debug(f"MCP [{cfg.name}]: no prompts or list_prompts unsupported — {e}")


async def load_mcp_capabilities(
    servers: list[MCPServerConfig],
) -> tuple[list[MCPCapabilities], Any, dict[str, Any]]:
    """
    Connect to all MCP servers. Load tools + resources + prompts.

    Returns:
        (capabilities_list, client)
        ``client`` is a ``MultiServerMCPClient`` (langchain-mcp-adapters ≥0.1.0): it is **not**
        an async context manager; keep the reference until the agent shuts down.

    Flow per server:
        1. client.get_tools()                  → tools list
        2. list resources via raw session      → build read_resource BaseTool
        3. list prompts via raw session        → build get_prompt BaseTool

    When ``transport=sse`` fails, retries once with ``streamable_http`` (common for modern MCP servers).
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError as exc:
        raise ImportError("langchain-mcp-adapters is required.\nInstall: uv add langchain-mcp-adapters") from exc

    transport_overrides: dict[str, str] = {}
    client: Any = None
    client_holder: dict[str, Any] = {}
    capabilities: list[MCPCapabilities] = []

    for attempt in range(2):
        if client is not None:
            await aclose_mcp_client(client)

        server_dict = _build_server_dict(servers, transport_overrides)
        client = MultiServerMCPClient(cast(Any, server_dict))
        client_holder = {"client": client, "_client_ref": weakref.ref(client)}
        logger.info(f"MCP: client ready for {list(server_dict)} (attempt {attempt + 1})")

        capabilities = []
        retry_as_streamable: list[str] = []

        for cfg in servers:
            transport_used = transport_overrides.get(cfg.name) or _adapter_transport(cfg.transport)
            cap = MCPCapabilities(server_name=cfg.name, transport_used=transport_used)

            try:
                await _populate_server_capabilities(client, client_holder, cfg, cap)
            except Exception as e:
                err_text = format_mcp_connect_error(cfg, e, transport_used=transport_used)
                logger.error(f"MCP [{cfg.name}]: capability load failed: {err_text}")
                cap.last_error = err_text
                if (
                    cfg.transport == "sse"
                    and transport_used == "sse"
                    and cfg.name not in transport_overrides
                ):
                    retry_as_streamable.append(cfg.name)

            capabilities.append(cap)
            logger.info(
                f"MCP [{cfg.name}]: {len(cap.tools)} tool(s), "
                f"{len(cap.resource_uris)} resource(s), "
                f"{len(cap.prompt_names)} prompt(s)"
            )

        if not retry_as_streamable or attempt == 1:
            break

        for name in retry_as_streamable:
            transport_overrides[name] = "streamable_http"
            logger.info(
                f"MCP [{name}]: sse connect failed — retrying with transport=streamable_http"
            )

    return capabilities, client, client_holder


def _make_resource_tool(
    server_name: str,
    client_holder: dict[str, Any],
    uris: list[str],
) -> BaseTool:
    """
    Wraps MCP read_resource into a BaseTool.

    Workers call:  read_resource_<server>(uri="file:///data/report.pdf")
    Returns:       text content or base64 blob as string

    The tool description lists all available URIs so the classifier
    knows what data is accessible.
    """
    uris_preview = ", ".join(uris)
    if len(uris) > 5:
        uris_preview += f" ... (+{len(uris) - 5} more)"

    from langchain_core.tools import StructuredTool

    class ResourceInput(BaseModel):
        uri: str = Field(description=f"URI of the resource to read. Available: {uris_preview}")

    async def read_resource(uri: str) -> str:
        ref = client_holder.get("_client_ref")
        client = ref() if ref is not None else client_holder.get("client")
        if client is None:
            return f"MCP client for {server_name!r} is closed; reconnect the agent session."
        try:
            blobs = await client.get_resources(server_name, uris=[uri])
            if not blobs:
                return f"No content found for URI: {uri}"
            parts = []
            for blob in blobs:
                if hasattr(blob, "as_string"):
                    parts.append(blob.as_string())
                else:
                    parts.append(str(blob))
            return "\n".join(parts)
        except Exception as e:
            return f"read_resource error for {uri!r}: {e}"

    return StructuredTool(
        name=f"read_resource_{server_name}",
        description=(f"Read data from the {server_name!r} MCP server resources. Available URIs: {uris_preview}"),
        args_schema=ResourceInput,
        coroutine=read_resource,
    )


def _make_prompt_tool(
    server_name: str,
    client_holder: dict[str, Any],
    prompt_names: list[str],
) -> BaseTool:
    """
    Wraps MCP get_prompt into a BaseTool.

    Workers call:  get_prompt_<server>(name="code_review", arguments='{"language":"python"}')
    Returns:       prompt messages as formatted string

    Use case:
      - Worker needs a standardised prompt template from the MCP server
      - e.g. code_review prompt, summarise prompt, translate prompt
    """
    names_str = ", ".join(prompt_names)

    import json

    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel

    class PromptInput(BaseModel):
        name: str = Field(description=f"Prompt name. Available: {names_str}")
        arguments: str = Field(default="{}", description="JSON string of arguments for the prompt template")

    async def get_prompt(name: str, arguments: str = "{}") -> str:
        ref = client_holder.get("_client_ref")
        client = ref() if ref is not None else client_holder.get("client")
        if client is None:
            return f"MCP client for {server_name!r} is closed; reconnect the agent session."
        try:
            args = json.loads(arguments) if arguments.strip() else {}
            messages = await client.get_prompt(server_name, name, arguments=args)
            parts = []
            for msg in messages:
                role = getattr(msg, "type", getattr(msg, "role", "message"))
                content = getattr(msg, "content", str(msg))
                parts.append(f"[{role}]\n{content}")
            return "\n\n".join(parts) if parts else f"No content for prompt {name!r}"
        except Exception as e:
            return f"get_prompt error for {name!r}: {e}"

    return StructuredTool(
        name=f"get_prompt_{server_name}",
        description=(
            f"Fetch a reusable prompt template from the {server_name!r} MCP server. Available prompts: {names_str}"
        ),
        args_schema=PromptInput,
        coroutine=get_prompt,
    )


async def connect_mcp_servers(
    servers: list[MCPServerConfig],
    agent: dict,
    agent_name: str = "Agent",
) -> tuple[Any, list[dict[str, Any]]]:
    """
    Connect to all MCP servers and inject capabilities into agent config.

    What gets added to agent dict:
        agent["tools"]       += all tools + resource_tools + prompt_tools
        agent["mcp_prompts"]  = {server_name: [prompt_name, ...]}
        agent["mcp_uris"]     = {server_name: [uri, ...]}

    Returns ``(client, server_rows)`` where *client* is the open MCP client and *server_rows*
    summarises each server for AGP / logging.

    Raises:
        MCPConnectionError: if the adapter is missing, the multi-server client cannot start,
        or any configured server fails its primary tool load (``get_tools``). On partial
        server failure, the shared client is closed before raising — callers must not use
        any returned capability handles from a failed connect attempt.
    """
    if not servers:
        return None, []

    try:
        caps, client, client_holder = await load_mcp_capabilities(servers)
    except ImportError as e:
        raise MCPConnectionError(str(e)) from e
    except Exception as e:
        logger.error(f"[{agent_name}] MCP connect failed: {e}")
        root = _unwrap_exception(e)
        raise MCPConnectionError(
            f"MCP: could not initialize client for {len(servers)} configured server(s): {root}"
        ) from e

    failed = [cap for cap in caps if cap.last_error is not None]
    empty_tools = [cap for cap in caps if cap.last_error is None and not cap.all_tools()]
    if empty_tools:
        detail = "; ".join(
            f"{c.server_name}: connected but returned 0 tools/resources/prompts" for c in empty_tools
        )
        await aclose_mcp_client(client, log_name=agent_name)
        raise MCPConnectionError(
            f"MCP: {len(empty_tools)} of {len(caps)} server(s) registered no callable tools — {detail}"
        )

    if failed:
        detail = "; ".join(f"{c.server_name}: {c.last_error}" for c in failed)
        await aclose_mcp_client(client, log_name=agent_name)
        hint = ""
        if any(
            s.transport == "sse" and (c.transport_used or "") == "streamable_http"
            for s in servers
            for c in failed
            if c.server_name == s.name
        ):
            hint = (
                " (sse was retried as streamable_http; if this still fails, "
                "set transport=streamable_http explicitly in mcp config)"
            )
        raise MCPConnectionError(
            f"MCP: {len(failed)} of {len(caps)} server(s) failed to connect — {detail}{hint}"
        )

    existing_names = {t.name for t in agent.get("tools", [])}
    new_tools: list[BaseTool] = []
    mcp_prompts: dict[str, list[str]] = {}
    mcp_uris: dict[str, list[str]] = {}

    for cap in caps:
        for t in cap.all_tools():
            if t.name not in existing_names:
                new_tools.append(t)
                existing_names.add(t.name)

        if cap.prompt_names:
            mcp_prompts[cap.server_name] = cap.prompt_names
        if cap.resource_uris:
            mcp_uris[cap.server_name] = cap.resource_uris

    agent["tools"] = agent.get("tools", []) + new_tools
    agent["mcp_prompts"] = mcp_prompts
    agent["mcp_uris"] = mcp_uris
    agent["_mcp_client_holder"] = client_holder

    resource_counts = {s: len(u) for s, u in mcp_uris.items()}
    logger.info(
        f"[{agent_name}] MCP ready: +{len(new_tools)} tools | prompts: {mcp_prompts} | resources: {resource_counts}"
    )

    server_rows: list[dict[str, Any]] = []
    for cap in caps:
        tools = cap.all_tools()
        catalog = _tool_catalog_entries(tools)
        names = [e["name"] for e in catalog]
        server_rows.append(
            {
                "name": cap.server_name,
                "ok": True,
                "error": None,
                "transport": cap.transport_used,
                "tool_count": len(tools),
                "tool_names": names,
                "tool_catalog": catalog,
                "tool_names_truncated": len(tools) > len(catalog),
            }
        )

    append_mcp_system_appendix_to_agent(agent, server_rows)

    return client, server_rows


MCP_SYSTEM_APPENDIX_MARKER = "=== MCP servers and tools ==="
_MCP_DESC_MAX = 220
_MCP_TOOLS_PER_SERVER_APPENDIX = 48


def mcp_configured_server_names(agent: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for s in agent.get("_mcp_servers") or []:
        nm = getattr(s, "name", None) or (s.get("name") if isinstance(s, dict) else None)
        if nm:
            names.append(str(nm))
    return names


def format_mcp_inventory_text(
    *,
    configured_names: list[str],
    server_rows: list[dict[str, Any]] | None,
) -> str:
    """Plain-text MCP inventory from agloom session state (no MCP tool / DB calls)."""
    rows = list(server_rows or [])
    by_name = {str(r.get("name") or ""): r for r in rows if r.get("name")}
    names = configured_names or list(by_name.keys())
    if not names:
        return "No MCP servers configured (set mcp.servers in .agloom/agloom.yaml)."

    lines: list[str] = ["MCP inventory (from agloom session — not the Super-Brain graph DB):"]
    for sname in names:
        row = by_name.get(sname)
        if row is None:
            lines.append(f"- {sname}: configured, not connected yet (send a message to connect)")
            continue
        if not row.get("ok"):
            err = row.get("error")
            lines.append(f"- {sname}: connect failed{(': ' + str(err)) if err else ''}")
            continue
        catalog_raw = row.get("tool_catalog")
        catalog: list[dict[str, str]] = []
        if isinstance(catalog_raw, list):
            for item in catalog_raw:
                if isinstance(item, dict):
                    n = str(item.get("name") or "").strip()
                    if n:
                        catalog.append(
                            {
                                "name": n,
                                "description": str(item.get("description") or "").strip(),
                            }
                        )
        if not catalog:
            for n in row.get("tool_names") or []:
                catalog.append({"name": str(n), "description": ""})
        lines.append(f"- {sname}: connected, {len(catalog)} tool(s)")
        for entry in catalog[:_MCP_TOOLS_PER_SERVER_APPENDIX]:
            n = entry["name"]
            desc = entry.get("description") or ""
            lines.append(f"    · {n}" + (f" — {desc}" if desc else ""))
        if len(catalog) > _MCP_TOOLS_PER_SERVER_APPENDIX:
            lines.append("    · … (more tools in tool schemas)")
    return "\n".join(lines)


def _normalize_tool_description(tool: BaseTool, *, max_len: int = _MCP_DESC_MAX) -> str:
    raw = getattr(tool, "description", None) or ""
    text = " ".join(str(raw).split())
    if not text:
        return ""
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def _tool_catalog_entries(tools: list[BaseTool], *, max_tools: int = 80) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for t in tools[:max_tools]:
        name = str(getattr(t, "name", "") or "").strip() or "?"
        desc = _normalize_tool_description(t)
        out.append({"name": name, "description": desc})
    return out


def build_mcp_system_appendix(
    server_rows: list[dict[str, Any]],
    *,
    mcp_prompts: dict[str, list[str]] | None = None,
    mcp_uris: dict[str, list[str]] | None = None,
) -> str:
    """Human-readable MCP tool inventory for the model (appended to string ``system_prompt``)."""
    ok_rows = [r for r in server_rows if r.get("ok")]
    if not ok_rows:
        return ""

    server_label = ", ".join(str(r.get("name") or "?") for r in ok_rows)
    lines = [
        "",
        MCP_SYSTEM_APPENDIX_MARKER,
        f"MCP servers connected this session: {server_label}.",
        "When the user asks which MCP servers are connected or what each MCP tool does: answer from this section, or call the bundled tool `list_mcp_servers` — do **not** call agsuperbrain `list_modules` / graph tools (those open the Kuzu DB and are for repo modules, not MCP wiring).",
        "Use MCP tools below for repo/graph search and Super-Brain capabilities after you know what is connected.",
        "",
    ]
    prompts_map = mcp_prompts or {}
    uris_map = mcp_uris or {}
    for row in ok_rows:
        sname = str(row.get("name") or "?")
        catalog_raw = row.get("tool_catalog")
        catalog: list[dict[str, str]] = []
        if isinstance(catalog_raw, list):
            for item in catalog_raw:
                if isinstance(item, dict):
                    n = str(item.get("name") or "").strip()
                    if n:
                        catalog.append(
                            {
                                "name": n,
                                "description": str(item.get("description") or "").strip(),
                            }
                        )
        if not catalog:
            names = [str(n) for n in (row.get("tool_names") or [])]
            catalog = [{"name": n, "description": ""} for n in names]
        truncated = bool(row.get("tool_names_truncated"))
        count_label = f"{len(catalog)}+" if truncated else str(len(catalog))
        lines.append(f"**{sname}** ({count_label} tool(s)):")
        for entry in catalog[:_MCP_TOOLS_PER_SERVER_APPENDIX]:
            n = entry["name"]
            desc = entry.get("description") or ""
            if desc:
                lines.append(f"  - `{n}` — {desc}")
            else:
                lines.append(f"  - `{n}`")
        if truncated and len(catalog) > _MCP_TOOLS_PER_SERVER_APPENDIX:
            lines.append("  - … additional tools (see tool schemas in the tool list)")
        prompt_names = prompts_map.get(sname) or []
        if prompt_names:
            preview = ", ".join(prompt_names[:24])
            if len(prompt_names) > 24:
                preview += ", …"
            lines.append(f"  Prompt templates: `get_prompt_{sname}` — {preview}")
        uris = uris_map.get(sname) or []
        if uris:
            lines.append(f"  Resources: `read_resource_{sname}` — {len(uris)} URI(s) available")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def append_mcp_system_appendix_to_agent(agent: dict[str, Any], server_rows: list[dict[str, Any]]) -> None:
    """Extend a string ``system_prompt`` once MCP tools are loaded (callable prompts unchanged)."""
    sp = agent.get("system_prompt")
    if not isinstance(sp, str):
        return
    if MCP_SYSTEM_APPENDIX_MARKER in sp:
        return
    appendix = build_mcp_system_appendix(
        server_rows,
        mcp_prompts=agent.get("mcp_prompts"),
        mcp_uris=agent.get("mcp_uris"),
    )
    if appendix:
        agent["system_prompt"] = sp.rstrip() + appendix


async def aclose_mcp_client(
    client: Any,
    *,
    log_name: str = "agent",
    client_holder: dict[str, Any] | None = None,
) -> None:
    """Best-effort shutdown for ``MultiServerMCPClient`` and similar (no reliable ``__aexit__``)."""
    if client_holder is not None:
        client_holder["client"] = None
    if client is None:
        return
    try:
        if hasattr(client, "__aexit__"):
            try:
                await client.__aexit__(None, None, None)
                return
            except NotImplementedError:
                logger.debug(
                    f"[{log_name}] MCP client __aexit__ not implemented "
                    f"(expected for MultiServerMCPClient)"
                )
        for meth_name in ("aclose", "close"):
            m = getattr(client, meth_name, None)
            if callable(m):
                try:
                    res = m()
                    if inspect.isawaitable(res):
                        await res
                except Exception as exc:
                    logger.debug(f"[{log_name}] MCP client {meth_name}: {exc!r}")
                return
    except Exception as exc:
        logger.debug(f"[{log_name}] MCP client cleanup: {exc!r}")
