# Models & providers

agloom-cli drives LangChain chat models through **`agloom-runtime`**. Specify a model with **`-m` / `--model`** using `"<provider>:<model-id>"`. Only the **first** colon separates provider from model; model ids may contain `/`, `:`, `@`, etc.

**LiteLLM**, **OpenRouter**, and **`lc:` / `init:`** routing are documented under [Broad-routing prefixes](#broad-routing-prefixes) below (they use aggregator or unified-initializer flows rather than the curated slug table).

## Quick reference

| Provider | Example | Env var(s) | pip extra | Models → |
| --- | --- | --- | --- | --- |
| OpenAI | `openai:gpt-4o` | `OPENAI_API_KEY` | `agloom[openai]` | [Models](https://platform.openai.com/docs/models) |
| Anthropic | `anthropic:claude-3-5-sonnet-20241022` | `ANTHROPIC_API_KEY` | `agloom[anthropic]` | [Models](https://docs.anthropic.com/en/docs/about-claude/models) |
| Google Gemini | `google:gemini-2.0-flash` | `GOOGLE_API_KEY` or `GEMINI_API_KEY` | `agloom[google-genai]` | [Gemini](https://ai.google.dev/gemini-api/docs/models/gemini) |
| Mistral | `mistralai:mistral-large-latest` | `MISTRAL_API_KEY` | `agloom[mistralai]` | [Models](https://docs.mistral.ai/getting-started/models/) |
| Groq | `groq:meta-llama/llama-3.3-70b-versatile` | `GROQ_API_KEY` | `agloom[groq]` | [Models](https://console.groq.com/docs/models) |
| xAI Grok | `xai:grok-3-latest` | `XAI_API_KEY` | `agloom[xai]` | [Models](https://docs.x.ai/docs/models) |
| DeepSeek | `deepseek:deepseek-chat` | `DEEPSEEK_API_KEY` | `agloom[deepseek]` | [API](https://api-docs.deepseek.com/) |
| Cerebras | `cerebras:llama-3.3-70b` | `CEREBRAS_API_KEY` | `agloom[cerebras]` | [Docs](https://inference-docs.cerebras.ai/) |
| Together | `together:meta-llama/Llama-3-70b-chat-hf` | `TOGETHER_API_KEY` | `agloom[together]` | [Models](https://docs.together.ai/docs/inference-models) |
| Fireworks | `fireworks:accounts/fireworks/models/...` | `FIREWORKS_API_KEY` | `agloom[fireworks]` | [Models](https://docs.fireworks.ai/models) |
| Perplexity | `perplexity:sonar` | `PERPLEXITY_API_KEY` | `agloom[perplexity]` | [Docs](https://docs.perplexity.ai/) |
| Cohere | `cohere:command-r-plus` | `COHERE_API_KEY` | `agloom[cohere]` | [Models](https://docs.cohere.com/docs/models) |
| Upstage | `upstage:solar-1-mini-chat` | `UPSTAGE_API_KEY` | `agloom[upstage]` | [Docs](https://developers.upstage.ai/) |
| IBM Watsonx | `ibm:ibm/granite-3-2-8b-instruct` | `WATSONX_API_KEY` | `agloom[ibm]` | [Docs](https://www.ibm.com/docs/en/watsonx) |
| Hugging Face Hub | `huggingface:HuggingFaceH4/zephyr-7b-beta` | `HUGGINGFACEHUB_API_TOKEN` | `agloom[huggingface]` | [Models](https://huggingface.co/models) |
| Ollama (local) | `ollama:llama3.2` | — | `agloom[ollama]` | [Library](https://ollama.com/library) |
| vLLM (OpenAI-compat) | `vllm:meta-llama/Llama-3-8b-instruct` | `OPENAI_API_KEY` (often dummy) | `agloom[openai]` | [Serving](https://docs.vllm.ai/) |
| NVIDIA NIM | `nvidia:meta/llama3-70b-instruct` | `NVIDIA_API_KEY` | `agloom[nvidia]` | [NIM](https://docs.nvidia.com/nim/) |
| SambaNova | `sambanova:Meta-Llama-3.3-70B-Instruct` | `SAMBANOVA_API_KEY` | `agloom[sambanova]` | [Docs](https://docs.sambanova.ai/) |
| Baseten | `baseten:llama-3-8b` | `BASETEN_API_KEY` | (upstream package) | [Baseten](https://www.baseten.co/) |
| Azure OpenAI | `azure_openai:gpt-4o` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` | `agloom[openai]` | [Azure](https://learn.microsoft.com/azure/ai-services/openai/) |
| Azure AI | `azure_ai:gpt-4o` | `AZURE_AI_API_KEY`, `AZURE_AI_ENDPOINT` | `agloom[azure-ai]` | [Azure AI](https://learn.microsoft.com/azure/ai-studio/) |
| AWS Bedrock | `bedrock:anthropic.claude-3-5-sonnet-20241022-v2:0` | AWS IAM | `agloom[aws]` | [Bedrock](https://docs.aws.amazon.com/bedrock/) |
| Vertex AI | `google_vertexai:gemini-2.0-flash` | gcloud ADC | `agloom[google-vertexai]` | [Vertex](https://cloud.google.com/vertex-ai/docs) |
| Anthropic on Vertex | `google_anthropic_vertex:claude-3-5-sonnet@20240620` | gcloud ADC | see LangChain docs | [Vertex](https://cloud.google.com/vertex-ai/generative-ai/docs/partner-models/use-claude) |
| Snowflake Cortex | `snowflake:snowflake-arctic` | Snowflake auth | `agloom[snowflake]` | [Cortex](https://docs.snowflake.com/en/user-guide/snowflake-cortex) |

Curated rows match `agloom --list-providers` (single source of truth in `provider_registry.py`).

### Hugging Face

This CLI documents the **Hub** path (`huggingface:…` + `HUGGINGFACEHUB_API_TOKEN`). Dedicated inference endpoints behave like any other **OpenAI-compatible server**: use **`vllm:`** (ChatOpenAI + `base_url`) and pass `-- --base-url https://your-endpoint/v1` after `--`.

## Broad-routing prefixes

When you need LangChain’s router or aggregators:

- **LiteLLM** (many backends):

  ```bash
  agloom -m "litellm:groq/llama-3.3-70b-versatile"
  ```

- **OpenRouter**:

  ```bash
  agloom -m "openrouter:anthropic/claude-3.5-sonnet"
  ```

- **Unified initializer** (`init_chat_model`):

  ```bash
  agloom -m "init:openai:gpt-4o"
  agloom -m "lc:groq:meta-llama/llama-3.3-70b-versatile"
  ```

Install the matching `langchain-*` extra (see `pip install 'agloom[litellm]'`, etc.).

## How the prefix works

Format: `<provider>:<model-id-which-may-contain-anything>`

**Only the first colon** separates provider from model:

```text
groq:meta-llama/llama-3.3-70b-versatile
↑ provider                   ↑ model (slash preserved)

bedrock:anthropic.claude-3-5-sonnet-20241022-v2:0
↑ provider   ↑ model (inner :0 is part of the model id)

openrouter:anthropic/claude-3.5-sonnet
↑ provider   ↑ vendor/model path for OpenRouter
```

Verify routing without calling the API:

```bash
agloom --resolve-model "bedrock:anthropic.claude-3-5-sonnet-20241022-v2:0"
```

## Choosing `--model` vs `--provider`

If the model id includes a curated **`provider:`** prefix, **`--provider`** is usually redundant.

Use **`--provider`** when:

- The model id has **no** prefix (for example a bare Hub id):  
  `agloom --provider huggingface --model BAAI/bge-small-en-v1.5`
- You want to **force** a backend that differs from the prefix (advanced).

The npm CLI maps **`--provider`** to `agloom-runtime --provider`.

## Local models

### Ollama (recommended)

Install [Ollama](https://ollama.com/), pull a model, then:

```bash
ollama pull llama3.2
agloom -m ollama:llama3.2
```

Default server is `http://localhost:11434`. For a remote daemon set **`OLLAMA_BASE_URL`** (or `OLLAMA_HOST`).

### vLLM, LM Studio, llama.cpp server, …

Any **OpenAI-compatible** HTTP API works with the **`vllm:`** slug (ChatOpenAI + `base_url`):

```bash
export OPENAI_API_KEY=dummy-non-empty
agloom -m "vllm:meta-llama/Llama-3-8b-instruct" -- --base-url http://localhost:8000/v1
```

Use the model name your server expects; point `--base-url` at its `/v1` root.

## API key precedence

Order (highest wins):

1. **`--api-key-env VAR`** — copies `VAR` into the provider’s standard env key inside the runtime (see [Flags](flags.md)).
2. **Process environment** (`export GROQ_API_KEY=…`).
3. **`agloom.yaml`** `api_keys` (when wired through library/YAML layers).
4. Otherwise the resolver raises a clear **missing key** error.

Prefer **`--api-key-env`** in scripts to avoid putting secrets in argv:

```bash
agloom --api-key-env MY_GROQ_KEY -m groq:meta-llama/llama-3.3-70b-versatile
```

## Auto-detection

If **`--model`** is omitted, the runtime picks the first provider whose env keys are set (priority order: OpenAI → Anthropic → Google → Mistral → Groq → xAI → …). Inspect the merged resolution with:

```bash
agloom --print-config
```

## Typos and missing extras

- Unknown slug close to a curated name → error suggests **`agloom --list-providers`**.
- Missing LangChain wheel → message looks like **`langchain-groq not installed. Run: pip install 'agloom[groq]'`**.
- Missing API key → names the env var and **`--api-key-env`**.

See [Troubleshooting](troubleshooting.md).
