# Installation

## Install from PyPI

=== "pip"

    ```bash
    pip install agloom
    ```

=== "uv"

    ```bash
    uv add agloom
    ```

=== "poetry"

    ```bash
    poetry add agloom
    ```

## Optional Extras

agloom supports multiple LLM providers. Install only what you need:

=== "pip"

    ```bash
    pip install agloom[groq]         # Groq (Llama, Mixtral)
    pip install agloom[nvidia]       # NVIDIA NIM
    pip install agloom[huggingface]  # HuggingFace endpoints
    pip install agloom[webhook]      # Webhook feedback (httpx)
    pip install agloom[all]          # All providers
    pip install agloom[docs]         # Documentation tools
    ```

=== "uv"

    ```bash
    uv add agloom[groq]
    uv add agloom[all]
    ```

## Verify Installation

```python
import agloom
print(agloom.__version__)  # → 0.1.1
```

## Environment Variables

Set your LLM provider API key:

=== "Groq"

    ```bash
    export GROQ_API_KEY="gsk_..."  # pragma: allowlist secret
    ```

=== "OpenAI"

    ```bash
    export OPENAI_API_KEY="sk-..."  # pragma: allowlist secret
    ```

=== "NVIDIA"

    ```bash
    export NVIDIA_API_KEY="nvapi-..."  # pragma: allowlist secret
    ```

### LangSmith (optional, auto-detected)

To enable tracing with LangSmith, set these environment variables. agloom auto-detects them — no code changes needed.

```bash
export LANGSMITH_API_KEY="lsv2_..."  # pragma: allowlist secret
export LANGSMITH_TRACING=true
export LANGSMITH_PROJECT="my-project"
```

To **disable** LangSmith tracing:

```bash
export LANGSMITH_TRACING=false
# or simply don't set LANGSMITH_API_KEY
```

See [Observability & LangSmith](../features/observability.md) for details.
