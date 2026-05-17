# Requirements

## Minimum Software Requirements

| Requirement       | Version | Notes                                                                                    |
| ----------------- | ------- | ---------------------------------------------------------------------------------------- |
| **Python**                | 3.12.x  | Required by `agsuperbrain`; install resolves NumPy 1.x for Super-Brain + `qdrant-client` |
| **pip**                   | 21.0+   | For installing from PyPI                                                                 |
| **uv** (optional)         | 0.4+    | Recommended for faster installs and dev workflow                                         |

## Runtime Dependencies

These are installed automatically with `pip install agloom` (see `[project] dependencies` in `pyproject.toml` for exact minimum versions):

| Package                       | Purpose                                                                                          |
| ----------------------------- | ------------------------------------------------------------------------------------------------ |
| `langchain`, `langgraph`      | Core agent graphs and LLM abstractions                                                           |
| `langchain-mcp-adapters`      | MCP server integration                                                                           |
| `langgraph-checkpoint-sqlite` | SQLite checkpointer dependency (LangGraph persistence)                                           |
| `fastapi`, `uvicorn[standard]`, `sse-starlette` | HTTP + SSE stack for the observability API and related serving paths            |
| `qdrant-client`               | Semantic query cache (`create_cache()`), vector similarity                                       |
| `pyyaml`, `tomli`             | Config and project metadata                                                                      |
| `httpx`                       | Async HTTP (tools, webhook feedback handler)                                                     |
| `tiktoken`                    | Token counting when available (`session` memory helpers)                                         |
| `agsuperbrain`                | Super-Brain local graph + MCP for the CLI ([docs](https://agsuperbrain.readthedocs.io/))         |

## Optional Dependencies — provider & feature extras

Installed via **named extras** only (e.g. `pip install 'agloom[openai,groq]'`). There is **no `agloom[all]`** extra: resolving every `langchain-*` provider in one install forces incompatible pins; combine the extras you need instead (see the comment in `pyproject.toml`).

| Extra          | Adds (typical)           | Purpose                                      |
| -------------- | ------------------------ | -------------------------------------------- |
| `openai`       | `langchain-openai`       | OpenAI chat models                           |
| `anthropic`    | `langchain-anthropic`    | Anthropic Claude                             |
| `huggingface`  | `langchain-huggingface`  | Hugging Face Inference / chat integrations   |
| `memory`       | `sentence-transformers`, `langchain-huggingface` | Embeddings for smart context / skill matching (`agloom[memory]`) |
| `groq`         | `langchain-groq`        | Groq Cloud (Llama, Mixtral, …)               |
| `nvidia`       | `langchain-nvidia-ai-endpoints` | NVIDIA NIM                             |
| `ws`           | `websockets`             | WebSocket transport for `agloom-runtime`     |
| `docs`         | MkDocs stack             | Local documentation builds                   |

Combine extras when needed, for example:

```bash
pip install 'agloom[openai,memory]'
pip install 'agloom[groq,nvidia]'
```

## Development Dependencies

For contributing to agloom:

| Package      | Purpose                         |
| ------------ | ------------------------------- |
| `ruff`       | Linting and formatting          |
| `pyrefly`    | Type checking                   |
| `pre-commit` | Git hooks for code quality      |
| `commitizen` | Conventional commit enforcement |

Install dev dependencies (from the repo, using the lockfile):

```bash
uv sync --group dev
```

**TypeScript clients (repo contributors):** CI also runs `npm test` in **`agloom_cli/`** and **`agloom_web/`** (Node **22+**). Install dependencies per package (`npm install`) before pushing UI or wire-parser changes.

## Operating System Support

agloom is pure Python and runs on:

- **Linux** (Ubuntu 20.04+, Debian 11+, RHEL 8+)
- **macOS** (12 Monterey+)
- **Windows** (10/11, Server 2019+)

## Hardware

No GPU required. agloom calls LLM APIs over the network. Minimum:

- 512 MB RAM (for the agent process)
- Network access to your LLM provider
