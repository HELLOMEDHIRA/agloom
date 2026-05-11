# Requirements

## Minimum Software Requirements

| Requirement | Version | Notes |
| --- | --- | --- |
| **Python** | 3.12.x | Required by `agsuperbrain`; install resolves NumPy 1.x for Super-Brain + `qdrant-client` |
| **pip** | 21.0+ | For installing from PyPI |
| **uv** (optional) | 0.4+ | Recommended for faster installs and dev workflow |

## Runtime Dependencies

These are installed automatically with `pip install agloom` (see `[project] dependencies` in `pyproject.toml` for exact minimum versions):

| Package | Purpose |
| --- | --- |
| `langchain`, `langgraph` | Core agent graphs and LLM abstractions |
| `langchain-mcp-adapters` | MCP server integration |
| `langchain-huggingface` | HuggingFace Inference API chat models |
| `qdrant-client` | Semantic query cache (`create_cache()`), vector similarity |
| `sentence-transformers` | Embeddings for smart context / skill matching |
| `pyyaml`, `tomli` | Config and project metadata |
| `httpx` | Async HTTP (tools, webhook feedback handler) |
| `tiktoken` | Token counting when available (`session` memory helpers) |
| `agsuperbrain` | Super-Brain local graph + MCP for the CLI ([docs](https://agsuperbrain.readthedocs.io/)) |

## Optional Dependencies

Installed via extras (e.g., `pip install agloom[groq]`):

| Extra | Adds | Purpose |
| --- | --- | --- |
| `groq` | `langchain-groq` | Groq Cloud (Llama, Mixtral, …) |
| `nvidia` | `langchain-nvidia-ai-endpoints` | NVIDIA NIM |
| `all` | both of the above | Convenience meta-extra |
| `docs` | MkDocs stack | Local documentation builds (`pip install agloom[docs]`) |

## Development Dependencies

For contributing to agloom:

| Package | Purpose |
| --- | --- |
| `ruff` | Linting and formatting |
| `pyrefly` | Type checking |
| `pre-commit` | Git hooks for code quality |
| `commitizen` | Conventional commit enforcement |

Install dev dependencies (from the repo, using the lockfile):

```bash
uv sync --group dev
```

## Operating System Support

agloom is pure Python and runs on:

- **Linux** (Ubuntu 20.04+, Debian 11+, RHEL 8+)
- **macOS** (12 Monterey+)
- **Windows** (10/11, Server 2019+)

## Hardware

No GPU required. agloom calls LLM APIs over the network. Minimum:

- 512 MB RAM (for the agent process)
- Network access to your LLM provider
