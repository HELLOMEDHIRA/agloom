"""MCP client wiring: ``MCPServerConfig``, connect helpers, capability merge for agents/workers.

Uses ``langchain-mcp-adapters``; ``connect_mcp_servers`` is invoked lazily from ``UnifiedAgent``.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, model_validator

from .logging_utils import get_logger

logger = get_logger(__name__)


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

    def to_client_dict(self) -> dict[str, Any]:
        if self.transport == "stdio":
            d: dict[str, Any] = {
                "command": self.command,
                "args": self.args,
                "transport": "stdio",
            }
            if self.env:
                d["env"] = self.env
        else:
            d = {"url": self.url, "transport": self.transport}
            if self.headers:
                d["headers"] = self.headers
        return d


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

    def all_tools(self) -> list[BaseTool]:
        """All BaseTool objects from this server — tools + resource_tool + prompt_tool."""
        result = list(self.tools)
        if self.resource_tool:
            result.append(self.resource_tool)
        if self.prompt_tool:
            result.append(self.prompt_tool)
        return result


async def load_mcp_capabilities(
    servers: list[MCPServerConfig],
) -> tuple[list[MCPCapabilities], Any]:
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
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError as exc:
        raise ImportError("langchain-mcp-adapters is required.\nInstall: uv add langchain-mcp-adapters") from exc

    server_dict = {cfg.name: cfg.to_client_dict() for cfg in servers}
    # langchain-mcp-adapters 0.1.0+: no ``async with MultiServerMCPClient`` — construct and use ``get_tools`` / ``session``.
    client = MultiServerMCPClient(server_dict)  # type: ignore[arg-type]
    logger.info(f"MCP: client ready for {list(server_dict)}")

    capabilities: list[MCPCapabilities] = []

    for cfg in servers:
        cap = MCPCapabilities(server_name=cfg.name)

        try:
            cap.tools = await client.get_tools(server_name=cfg.name)

            try:
                async with client.session(cfg.name) as session:
                    res_response = await session.list_resources()
                    uris = [str(r.uri) for r in res_response.resources]
                    cap.resource_uris = uris

                if uris:
                    cap.resource_tool = _make_resource_tool(
                        server_name=cfg.name,
                        client=client,
                        uris=uris,
                    )
                    logger.info(f"MCP [{cfg.name}]: {len(uris)} resource(s) → tool 'read_resource_{cfg.name}'")
            except Exception as e:
                # Many stdio MCP servers expose tools only (no resources); adapters may still error on list_resources.
                logger.debug(f"MCP [{cfg.name}]: no resources or list_resources unsupported — {e}")

            try:
                async with client.session(cfg.name) as session:
                    prompt_response = await session.list_prompts()
                    names = [p.name for p in prompt_response.prompts]
                    cap.prompt_names = names

                if names:
                    cap.prompt_tool = _make_prompt_tool(
                        server_name=cfg.name,
                        client=client,
                        prompt_names=names,
                    )
                    logger.info(f"MCP [{cfg.name}]: {len(names)} prompt(s) {names} → tool 'get_prompt_{cfg.name}'")
            except Exception as e:
                logger.debug(f"MCP [{cfg.name}]: no prompts or list_prompts unsupported — {e}")

        except Exception as e:
            logger.error(f"MCP [{cfg.name}]: capability load failed: {e}")
            cap.last_error = str(e)

        capabilities.append(cap)
        logger.info(
            f"MCP [{cfg.name}]: {len(cap.tools)} tool(s), "
            f"{len(cap.resource_uris)} resource(s), "
            f"{len(cap.prompt_names)} prompt(s)"
        )

    return capabilities, client


def _make_resource_tool(
    server_name: str,
    client: Any,
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
    client: Any,
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
        or any configured server fails its primary tool load (``get_tools``).
    """
    if not servers:
        return None, []

    try:
        caps, client = await load_mcp_capabilities(servers)
    except ImportError as e:
        raise MCPConnectionError(str(e)) from e
    except Exception as e:
        logger.error(f"[{agent_name}] MCP connect failed: {e}")
        raise MCPConnectionError(
            f"MCP: could not initialize client for {len(servers)} configured server(s): {e}"
        ) from e

    failed = [cap for cap in caps if cap.last_error is not None]
    if failed:
        detail = "; ".join(f"{c.server_name}: {c.last_error}" for c in failed)
        await aclose_mcp_client(client, log_name=agent_name)
        raise MCPConnectionError(
            f"MCP: {len(failed)} of {len(caps)} server(s) failed to connect — {detail}"
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

    resource_counts = {s: len(u) for s, u in mcp_uris.items()}
    logger.info(
        f"[{agent_name}] MCP ready: +{len(new_tools)} tools | prompts: {mcp_prompts} | resources: {resource_counts}"
    )

    server_rows: list[dict[str, Any]] = []
    for cap in caps:
        tools = cap.all_tools()
        names = [getattr(t, "name", "?") for t in tools]
        server_rows.append(
            {
                "name": cap.server_name,
                "ok": True,
                "error": None,
                "tool_count": len(tools),
                "tool_names": names[:80],
                "tool_names_truncated": len(names) > 80,
            }
        )

    return client, server_rows


async def aclose_mcp_client(client: Any, *, log_name: str = "agent") -> None:
    """Best-effort shutdown for ``MultiServerMCPClient`` and similar (no reliable ``__aexit__``)."""
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
