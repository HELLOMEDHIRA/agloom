# Config & environment

## `agloom.yaml`

Optional YAML layers configure defaults without long command lines. **Precedence** (low → high):

1. Built-in CLI defaults  
2. User file: **`~/.agloom/agloom.yaml`**  
3. **Walk-up** `./agloom.yaml` from the current working directory (nearest wins toward disk root)  
4. **`AGLOOM_*`** environment variables (see below)  
5. **`--config /path/to/agloom.yaml`** explicit file  
6. **Other CLI flags** (highest) — except **`multiline`**, which is **YAML-only** (TUI compose). Execution routing pattern is **not** user-configurable; the runtime classifier selects it.

### Supported keys

Validated fields (unknown keys are preserved via passthrough for forward compatibility):

| Key | Type | Purpose |
| --- | --- | --- |
| `model` | string | Default `-m` |
| `provider` | string | Default `--provider` |
| `temperature` | number | Sampling temperature |
| `max_tokens` | integer | Max output tokens |
| `multiline` | boolean | TUI compose: `true` = blank Enter sends (default **true** if omitted); `false` = single-line |
| `system_prompt` | string | Inline system prompt |
| `system_prompt_file` | string | Path to prompt file |
| `store` | string | AGP EventStore backend: `none`, `memory`, or `sqlite` |
| `store_path` | string | SQLite path for `store=sqlite` |
| `memory` | string | Session memory backend hint (`sqlite`, `in-memory`, `none`, …) |
| `memory_path` | string | SQLite session memory path |
| `skills_dir` | string | Skills **disk mirror** directory (defaults to `.agloom/skills` under cwd when omitted; see [Flags](flags.md)) |
| `summarizer_model` | string | Summarizer model id |
| `auto_summarize` | boolean | Toggle auto summarization |
| `session_max_turns` | integer | Session window (default **50**; maps from `memory.max_turns`) |
| `mcp` | array | Strings `name:path` or `{ name, config }` objects |

Flat keys **`no_memory`** and **`no_skills`** are stripped when YAML is loaded — they are not supported configuration.

### Nested `memory` and `skills` (rich YAML)

Rich layouts may nest tuning fields:

```yaml
memory:
  enabled: true
  max_turns: 50
  auto_summarize: true
  path: .agloom/session_memory.sqlite
skills:
  enabled: true
  max_skills: 30
  dir: .agloom/skills
```

**`enabled: false` is ignored** for both blocks: you cannot disable durable session memory or the skills subsystem from YAML alone; other fields still merge (for example `max_turns` → `session_max_turns`, `path` → `memory_path`, `dir` → `skills_dir`). A bare `memory.enabled: true` continues to imply `memory: sqlite` when no backend string is present.

### Minimal example

```yaml
model: groq:meta-llama/llama-3.3-70b-versatile
temperature: 0
```

### Richer example

```yaml
model: openai:gpt-4o
provider: openai
temperature: 0.2
store: sqlite
store_path: .agloom/agp_events.db
memory: sqlite
memory_path: .agloom/session_memory.sqlite
session_max_turns: 30
auto_summarize: true
summarizer_model: openai:gpt-4o-mini
mcp:
  - fs: ./mcp/filesystem.yaml
  - name: gh
    config: ./mcp/github.yaml
```

Relative MCP paths resolve against the YAML file’s directory.

### Session marker (`.agloom/sessions/*.json`)

Each session file includes an `effective_config` snapshot that **normally embeds `api_key_secret`** (the API key value read from the resolved env var) so resume works without the shell env. Do not commit `.agloom/sessions/` to git. Set **`AGLOOM_OMIT_API_KEY_FROM_SESSION=1`** for a names-only snapshot (no `api_key_secret`). **`api_key_env`** / **`api_key_env_nonempty`** name the env var used for that secret (explicit **`--api-key-env`** remap, or the first non-empty canonical key for the provider). **`provider_primary_api_key_env`** is written only when it differs from **`api_key_env`** (e.g. remap layouts). **`provider_credential_env`** lists each canonical env var for **`provider_resolved`** and whether it was non-empty at process start. **`provider_primary_credential_present`** is `true` when any canonical var for the resolved slug was set, or — when **`provider_resolved`** is `null` — when any curated provider API key env var was set at process start.

## Environment variables

### CLI / bridge

| Variable          | Purpose                                                                      |
| ----------------- | ---------------------------------------------------------------------------- |
| `AGLOOM_RUNTIME`  | Override executable for Python bridge (default: `agloom-runtime` on `PATH`). |
| `AGLOOM_MODEL`    | Default model id (wired where runtime honors env).                           |
| `AGLOOM_PROVIDER` | Default provider slug for unprefixed / ambiguous ids (Python resolver).      |
| `AGLOOM_BANNER`   | Set `0` / `false` to suppress the stderr startup banner.                     |
| `AGLOOM_OMIT_API_KEY_FROM_SESSION` | When `1` / `true`, session JSON omits `api_key_secret` (names-only snapshot). |

### Per-provider API keys (curated)

Use **`agloom --list-providers`** for the authoritative env column. Common keys:

| Variable                                        | Typical provider                       |
| ----------------------------------------------- | -------------------------------------- |
| `OPENAI_API_KEY`                                | OpenAI, Azure OpenAI-style, vLLM dummy |
| `ANTHROPIC_API_KEY`                             | Anthropic                              |
| `GOOGLE_API_KEY`, `GEMINI_API_KEY`              | Google Gemini                          |
| `MISTRAL_API_KEY`                               | Mistral AI                             |
| `GROQ_API_KEY`                                  | Groq                                   |
| `XAI_API_KEY`                                   | xAI                                    |
| `COHERE_API_KEY`                                | Cohere                                 |
| `DEEPSEEK_API_KEY`                              | DeepSeek                               |
| `TOGETHER_API_KEY`                              | Together                               |
| `FIREWORKS_API_KEY`                             | Fireworks                              |
| `PERPLEXITY_API_KEY`                            | Perplexity                             |
| `UPSTAGE_API_KEY`                               | Upstage                                |
| `WATSONX_API_KEY`                               | IBM Watsonx                            |
| `HUGGINGFACEHUB_API_TOKEN`                      | Hugging Face Hub                       |
| `CEREBRAS_API_KEY`                              | Cerebras                               |
| `NVIDIA_API_KEY`                                | NVIDIA NIM                             |
| `SAMBANOVA_API_KEY`                             | SambaNova                              |
| `BASETEN_API_KEY`                               | Baseten                                |
| `OPENROUTER_API_KEY`                            | OpenRouter                             |
| `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` | Azure OpenAI                           |
| `AZURE_AI_API_KEY`, `AZURE_AI_ENDPOINT`         | Azure AI                               |

### Cloud / IAM

| Variable                                       | Purpose                                           |
| ---------------------------------------------- | ------------------------------------------------- |
| `AWS_PROFILE`, `AWS_REGION`, standard AWS vars | Amazon Bedrock                                    |
| `GOOGLE_APPLICATION_CREDENTIALS`, gcloud ADC   | Vertex AI, Anthropic on Vertex                    |
| Snowflake connector env / session params       | Snowflake Cortex (see LangChain + Snowflake docs) |

### Local servers

| Variable                           | Purpose                          |
| ---------------------------------- | -------------------------------- |
| `OLLAMA_BASE_URL`, `OLLAMA_HOST`   | Ollama HTTP endpoint             |
| `VLLM_BASE_URL`, `OPENAI_BASE_URL` | OpenAI-compatible base URL hints |

### Web search (CLI tools)

| Variable                 | Purpose                           |
| ------------------------ | --------------------------------- |
| `AGLOOM_SEARCH_PROVIDER` | e.g. `tavily`, `brave`, `searxng` |
| Provider-specific keys   | As required by search integration |

See [Models & providers](models.md) and [Built-in CLI tools](../agloom/features/cli-tools.md).
