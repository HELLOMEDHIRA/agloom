# LLM resolution (`agloom.llm`)

**`create_agent`** accepts a LangChain chat model instance **or** a string descriptor (`"groq:meta-llama/..."`, `"openai:gpt-4o"`, …). When you build **your own** factory (custom YAML loader, runtime bootstrap, tests), use the same resolver the library uses.

## Primary entry points

| Symbol                              | Use                                                                                                  |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------- |
| **`get_model`**                     | Resolve a provider/model string (and optional patch dict) to a chat model instance                   |
| **`try_resolve_llm_from_api_keys`** | Pick a default model from environment keys (TTY vs non-interactive behavior differs — see docstring) |
| **`describe_llm`**                  | Human-readable description of a bound model                                                          |
| **`split_provider_prefix`**         | Split `"provider:rest"` tokens                                                                       |

Errors: **`MissingProviderApiKey`**, **`MissingProviderDependency`** — raised when keys or optional extras are absent.

## Conventions

Resolution semantics match **`create_agent`** and **`agloom-runtime`**: explicit **`provider:model_id`** prefixes, LiteLLM / `init:` / `lc:` bridges, and **`pyproject.toml`** optional extras (`agloom[groq]`, etc.). The module docstring in **`agloom/llm/model_resolver.py`** lists provider tables and links to LangChain integration docs.

```python
from agloom.llm import get_model

llm = await get_model("groq:meta-llama/llama-4-scout-17b-16e-instruct")
```

For patching temperature, base URL, or API keys from config dicts, use the same **`normalize_provider_slug`** / **`spread_llm_options_for_provider`** pipeline internally consumed by **`get_model`** (see **`agloom.llm.llm_provider_params`** if you extend YAML loaders).

## Unprefixed `org/model` ids

When you omit a `provider:` prefix, **`get_model`** can infer the backend from the first path segment:

| Model id | When it auto-routes |
| -------- | ------------------- |
| `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` set and `langchain-deepseek` installed |
| `meta-llama/llama-…` | Often Groq when `GROQ_API_KEY` is set (alias) |
| `mistralai/mistral-…` | `MISTRAL_API_KEY` set |

If both Groq and Ollama env hints are set, or no org match applies, resolution fails with an explicit error — use `groq:…`, `ollama:…`, or `AGLOOM_PROVIDER`. Prefer **`provider:model`** prefixes in production configs.
