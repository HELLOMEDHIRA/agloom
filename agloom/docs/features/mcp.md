# MCP Server Integration

agloom integrates with the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) to discover and use tools from external servers.

## How It Works

1. You pass `mcp_servers=[...]` to `create_agent` — **no network I/O at construction**
2. On the **first** `ainvoke` / `astream` call, agloom lazily connects to all MCP servers
3. Discovered tools are merged into the agent's tool list automatically
4. Use `async with agent:` or `await agent.aclose()` to cleanly disconnect

## Configuration

Import `MCPServerConfig` and define your servers:

```python
from agloom.mcp_support import MCPServerConfig
from agloom import create_agent

async def main():
    agent = await create_agent(
        model=llm,
        mcp_servers=[
            MCPServerConfig(
                name="filesystem",
                transport="stdio",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", "/data"],
            ),
            MCPServerConfig(
                name="weather",
                transport="sse",
                url="http://localhost:8000/mcp",
            ),
        ],
        name="mcp-agent",
    )
```

!!! warning "Context manager required"
    Always use `async with` or call `await agent.aclose()` to close MCP connections:

    ```python
    async with await create_agent(model=llm, mcp_servers=[...], name="mcp-agent") as agent:
        result = await agent.ainvoke("List files in /data")
    # MCP connections closed automatically
    ```

## Transport Types

| Transport         | Use case                            | Required fields                                |
| ----------------- | ----------------------------------- | ---------------------------------------------- |
| `stdio`           | Local process (npx, python, etc.)   | `command`, `args` (optional), `env` (optional) |
| `sse`             | Remote HTTP with Server-Sent Events | `url`                                          |
| `streamable_http` | Remote HTTP with streaming          | `url`, `headers` (optional)                    |
| `http`            | Simple HTTP endpoint                | `url`, `headers` (optional)                    |

## MCPServerConfig Fields

```python
MCPServerConfig(
    name="server-name",          # Required: unique identifier
    transport="stdio",           # Required: "stdio" | "sse" | "streamable_http" | "http"

    # For stdio transport:
    command="npx",               # Required for stdio
    args=["-y", "package"],      # Optional: command arguments
    env={"KEY": "value"},        # Optional: environment variables

    # For HTTP transports:
    url="http://...",            # Required for sse/http
    headers={"Auth": "Bearer"}, # Optional: HTTP headers

    timeout=30.0,                # Connection timeout in seconds (default: 30)
)
```

## What Gets Discovered

When the MCP connection is established, agloom loads:

- **Tools** — automatically added to the agent's tool list
- **Resources** — available as resource tools (if the server exposes them)
- **Prompts** — stored for prompt injection (if the server exposes them)

Each tool's **name** and **description** (from the MCP server's schema) are captured at connect time.

## Session inventory (no graph DB)

agloom keeps an in-memory catalog after connect (`_mcp_server_rows` on the agent config). You do **not** need to call MCP tools such as agsuperbrain **`list_modules`** to answer "what MCP servers are connected?" — that tool queries the Super-Brain **Kuzu graph database**, not agloom's wiring.

### System prompt appendix

For string `system_prompt` values, agloom appends a section marked **`=== MCP servers and tools ===`** with:

- Connected server names
- Per-tool lines: `` `tool_name` — short description `` (descriptions truncated to ~220 characters)

The model is instructed to answer MCP inventory questions from this section.

### CLI meta tool: `list_mcp_servers`

When **`cli_tools=True`**, the bundled meta tool **`list_mcp_servers`** returns the same inventory from session state (no MCP or DB I/O). Use it when the user asks what MCP tools exist or what each one does.

!!! tip "agsuperbrain"
    **`list_modules`** lists **repository modules inside the graph** — not MCP servers. For MCP wiring, use the appendix, **`list_mcp_servers`**, or the CLI **`/mcp`** slash command.

### AGP event: `runtime.mcp.servers`

After the first successful MCP connect in a session, the runtime emits:

```jsonc
{
  "type": "runtime.mcp.servers",
  "data": {
    "server_names": ["agsuperbrain"],
    "servers": [
      {
        "name": "agsuperbrain",
        "ok": true,
        "tool_count": 12,
        "tool_names": ["search_code", "…"],
        "tool_catalog": [
          { "name": "search_code", "description": "Semantic search over the repository." }
        ],
        "tool_names_truncated": false
      }
    ]
  }
}
```

Clients (CLI metrics sidebar, web UI) merge **`tool_names`** into the session tool list and may show **`tool_catalog`** previews. See [AGP specification](../protocol/agp.md).

## Example: Filesystem + Database

```python
async with await create_agent(
    model=llm,
    mcp_servers=[
        MCPServerConfig(
            name="filesystem",
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/home/user/docs"],
        ),
        MCPServerConfig(
            name="postgres",
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/mydb"],
            env={"PGPASSWORD": "secret"},
        ),
    ],
    name="data-agent",
) as agent:
    result = await agent.ainvoke("Find all .csv files and query the users table")
    print(result.output)
```

## Combining MCP with Local Tools

MCP tools are merged with any tools you pass to `create_agent`:

```python
from langchain_core.tools import tool

@tool
def word_count(text: str) -> str:
    """Count whitespace-separated words (safe — never eval user input)."""

    return str(len(text.split()))

async def main():
    agent = await create_agent(
        model=llm,
        tools=[word_count],          # local tool
        mcp_servers=[mcp_config],   # + MCP tools discovered at runtime
        name="hybrid-agent",
    )
```

## Validation

```python
# stdio requires command
MCPServerConfig(name="x", transport="stdio")
# ValueError: [x] stdio transport requires 'command'

# HTTP transports require url
MCPServerConfig(name="x", transport="sse")
# ValueError: [x] sse transport requires 'url'
```
