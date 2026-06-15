# LLM resolution

**`create_agent`** accepts either a LangChain chat model **or** a string like `"groq:meta-llama/llama-3.3-70b-versatile"`. Use the same resolution rules when you load models from YAML, CI, or a custom runtime bootstrap.

---

## Resolve a model string

```python
from agloom.llm import get_model

llm = await get_model("groq:meta-llama/llama-4-scout-17b-16e-instruct")
agent = await create_agent(model=llm, name="demo")
```

| Helper | Use |
| ------ | --- |
| `get_model` | Turn a descriptor into a chat model instance |
| `try_resolve_llm_from_api_keys` | Pick a default from environment keys (interactive vs CI behavior differs) |
| `describe_llm` | Log-friendly description of a bound model |
| `split_provider_prefix` | Split `provider:model_id` tokens |

Missing keys or optional extras raise clear errors (`MissingProviderApiKey`, `MissingProviderDependency`).

---

## Naming conventions

| Style | Example |
| ----- | ------- |
| **Recommended** | `groq:meta-llama/llama-3.3-70b-versatile`, `openai:gpt-4o` |
| LiteLLM bridge | `litellm:provider/model` |
| LangChain init | `lc:package:ClassName` |

Install provider extras as needed: `pip install agloom[groq]`, `agloom[openai]`, etc.

**Temperature and sampling** are set on the model instance (e.g. `ChatGroq(temperature=0.2)`), not on `create_agent`.

---

## Unprefixed `org/model` ids

Omitting the provider prefix works in some environments (e.g. `deepseek/deepseek-chat` when `DEEPSEEK_API_KEY` is set). Production configs should use explicit **`provider:model`** prefixes to avoid ambiguous routing when multiple keys are present.

---

## Qwen3 / vLLM / LiteLLM and tool calling

Self-hosted **Qwen3** models (e.g. `litellm:qwen36fp8`, `vllm:Qwen/...`) use Jinja chat templates that are strict about message shape. Agloom handles this inside REACT and worker agents:

| Behavior | Detail |
| -------- | ------ |
| **Qwen detection** | Model id contains `qwen` or `qwq` → `tool_choice=auto` on all tool-bearing model calls |
| **Other providers** | Opening turn only → `tool_choice=required` (Groq-style); follow-ups use provider default |
| **User content** | LangChain multimodal content blocks are flattened to plain strings before each LLM call |

If you still see ``No user query found in messages`` after upgrading agloom:

1. Confirm the integrator is on a build that includes `agloom.llm.qwen_compat`.
2. On the vLLM server, enable auto tool choice and a Qwen-compatible parser (e.g. `--enable-auto-tool-choice`, `--tool-call-parser qwen3_coder`).
3. See [Errors — LiteLLM / vLLM / Qwen3](../configuration/errors.md).

``react_force_tool_choice_on_user_turn=False`` disables **tool_choice overrides only**; message flattening still runs.

---

## See also

- [All parameters — `model`](../configuration/parameters.md#core)
- [CLI models & providers](https://agloom.readthedocs.io/en/latest/_packages/agloom_cli/models/)
- [Installation](../getting-started/installation.md)
