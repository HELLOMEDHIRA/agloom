# Requirements

## Minimum Software Requirements

| Requirement | Version | Notes |
|------------|---------|-------|
| **Python** | 3.11+ | Uses `asyncio`, type hints, `StrEnum`, `ExceptionGroup` |
| **pip** | 21.0+ | For installing from PyPI |
| **uv** (optional) | 0.4+ | Recommended for faster installs and dev workflow |

## Runtime Dependencies

These are installed automatically with `pip install agloom`:

| Package | Version | Purpose |
|---------|---------|---------|
| `langchain` | ≥ 1.2.13 | Core LLM abstractions |
| `langchain-classic` | ≥ 1.0.3 | Legacy compatibility layer |
| `langchain-mcp-adapters` | ≥ 0.2.2 | MCP server integration |
| `langgraph` | ≥ 1.1.3 | State graphs, stores, checkpointing |
| `qdrant-client` | ≥ 1.17.1 | Semantic query cache (via `create_cache()`, uses Qdrant for vector similarity) |
| `requests` | ≥ 2.33.0 | HTTP utilities |
| `sentence-transformers` | ≥ 5.3.0 | Embedding-based skill matching |

## Optional Dependencies

Installed via extras (e.g., `pip install agloom[groq]`):

| Extra | Package | Version | Purpose |
|-------|---------|---------|---------|
| `groq` | `langchain-groq` | ≥ 1.1.2 | Groq Cloud (Llama, Mixtral) |
| `huggingface` | `langchain-huggingface` | ≥ 1.2.1 | HuggingFace Inference |
| `nvidia` | `langchain-nvidia-ai-endpoints` | ≥ 1.2.1 | NVIDIA NIM |
| `webhook` | `httpx` | ≥ 0.27.0 | Async webhook feedback handler |
| `docs` | `mkdocs`, `mkdocs-material` | latest | Documentation generation |

## Development Dependencies

For contributing to agloom:

| Package | Purpose |
|---------|---------|
| `ruff` | Linting and formatting |
| `pyrefly` | Type checking |
| `pre-commit` | Git hooks for code quality |
| `commitizen` | Conventional commit enforcement |

Install all dev dependencies:

```bash
uv sync --all-extras
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
