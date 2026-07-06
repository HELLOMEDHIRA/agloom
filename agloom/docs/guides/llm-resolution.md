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
| --- | --- |
| `get_model` | Turn a descriptor into a chat model instance |
| `try_resolve_llm_from_api_keys` | Pick a default from environment keys (interactive vs CI behavior differs) |
| `describe_llm` | Log-friendly description of a bound model |
| `split_provider_prefix` | Split `provider:model_id` tokens |

Missing keys or optional extras raise clear errors (`MissingProviderApiKey`, `MissingProviderDependency`).

---

## Naming conventions

| Style | Example |
| --- | --- |
| **Recommended** | `groq:meta-llama/llama-3.3-70b-versatile`, `openai:gpt-4o` |
| LiteLLM bridge | `litellm:provider/model` |
| LangChain init | `lc:package:ClassName` |

Install provider extras as needed: `pip install agloom[groq]`, `agloom[openai]`, etc.

**Temperature and sampling** are set on the model instance (e.g. `ChatGroq(temperature=0.2)`), not on `create_agent`.

---

## Unprefixed `org/model` ids

Omitting the provider prefix works in some environments (e.g. `deepseek/deepseek-chat` when `DEEPSEEK_API_KEY` is set). Production configs should use explicit **`provider:model`** prefixes to avoid ambiguous routing when multiple keys are present.

---

## Strict chat templates and tool calling

Some providers — especially **self-hosted inference** (vLLM, SGLang), **LiteLLM routers**, and models with strict Jinja chat templates — reject malformed message lists or forced `tool_choice` on follow-up turns. Agloom handles this inside REACT and worker agents via `agloom.llm.chat_template_compat`:

| Behavior | Detail |
| --- | --- |
| **Strict-template detection** | `uses_strict_chat_template()` — vLLM/LiteLLM routing, opaque model groups, or model ids with known strict-template markers |
| **tool_choice** | Strict-template models: **no override** (provider default). Groq/Cerebras-style: `required` on opening turn only |
| **User content** | LangChain multimodal content blocks are flattened to plain strings before each LLM call |

If you still see ``No user query found in messages`` after upgrading agloom:

1. Confirm the integrator is on a build that includes `agloom.llm.chat_template_compat`.
2. On the inference server, enable auto tool choice and the **tool-call parser** that matches your model family (e.g. vLLM `--enable-auto-tool-choice` with the appropriate `--tool-call-parser`).
3. See [Errors — strict chat templates](../configuration/errors.md).

``react_force_tool_choice_on_user_turn=False`` disables **tool_choice overrides only**; message flattening still runs.

---

## See also

- [All parameters — `model`](../configuration/parameters.md#core)
- [CLI models & providers](https://agloom.readthedocs.io/en/latest/_packages/agloom_cli/models/)
- [Installation](../getting-started/installation.md)
