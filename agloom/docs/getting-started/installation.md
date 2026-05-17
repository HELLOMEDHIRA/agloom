# Installation

## Install from PyPI

=== "pip"

    ```bash
    pip install agloom
    ```

    If dependency resolution pulls in **NumPy 2.x** and you hit binary or stack issues, constrain before or with the install (this matches the repo’s `uv` override):

    ```bash
    pip install "numpy>=1.26.4,<2" agloom
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
    pip install agloom[openai]       # OpenAI
    pip install agloom[anthropic]   # Anthropic
    pip install agloom[huggingface] # Hugging Face Inference / chat stack
    pip install agloom[memory]     # sentence-transformers + HF (smart context / skills)
    pip install agloom[groq]         # Groq (Llama, Mixtral)
    pip install agloom[nvidia]     # NVIDIA NIM
    pip install 'agloom[groq,nvidia]'   # combine named extras (there is no agloom[all])
    pip install agloom[docs]         # MkDocs (same stack as dev docs builds)
    ```

=== "uv"

    ```bash
    uv add agloom[openai]
    uv add agloom[memory]
    uv add agloom[groq]
    uv add 'agloom[groq,nvidia]'
    ```

## Verify Installation

```python
import agloom
print(agloom.__version__)  # installed version from importlib.metadata
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
