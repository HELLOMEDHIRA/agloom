# Config & environment

## `agloom.yaml`

Optional YAML layers configure defaults without long command lines. **Precedence** (low → high):

1. Built-in CLI defaults  
2. User file: **`~/.agloom/agloom.yaml`**  
3. **Walk-up** `./agloom.yaml` from the current working directory (nearest wins toward disk root)  
4. **`AGLOOM_*`** environment variables (see below)  
5. **`--config /path/to/agloom.yaml`** explicit file  
6. **CLI flags** (highest)

### Supported keys

Validated fields (unknown keys are preserved via passthrough for forward compatibility):

| Key                  | Type     | Purpose                                           |          |                |
| -------------------- | -------- | ------------------------------------------------- | -------- | -------------- |
| `model`              | string   | Default `-m`                                      |          |                |
| `provider`           | string   | Default `--provider`                              |          |                |
| `temperature`        | number   | Sampling temperature                              |          |                |
| `max_tokens`         | integer  | Max output tokens                                 |          |                |
| `pattern`            | string   | Routing pattern name                              |          |                |
| `system_prompt`      | string   | Inline system prompt                              |          |                |
| `system_prompt_file` | string   | Path to prompt file                               |          |                |
| `store`              | `none` \ | `memory` \                                        | `sqlite` | AGP EventStore |
| `store_path`         | string   | SQLite path                                       |          |                |
| `memory`             | string   | Session memory backend hint                       |          |                |
| `memory_path`        | string   | SQLite session memory path                        |          |                |
| `no_memory`          | boolean  | Minimal memory                                    |          |                |
| `no_skills`          | boolean  | Disable skills mirror                             |          |                |
| `skills_dir`         | string   | Skills directory                                  |          |                |
| `summarizer_model`   | string   | Summarizer model id                               |          |                |
| `auto_summarize`     | boolean  | Toggle auto summarization                         |          |                |
| `session_max_turns`  | integer  | Session window                                    |          |                |
| `mcp`                | array    | Strings `name:path` or `{ name, config }` objects |          |                |

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
pattern: react
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

## Environment variables

### CLI / bridge

| Variable          | Purpose                                                                      |
| ----------------- | ---------------------------------------------------------------------------- |
| `AGLOOM_RUNTIME`  | Override executable for Python bridge (default: `agloom-runtime` on `PATH`). |
| `AGLOOM_MODEL`    | Default model id (wired where runtime honors env).                           |
| `AGLOOM_PROVIDER` | Default provider slug for unprefixed / ambiguous ids (Python resolver).      |
| `AGLOOM_PATTERN`  | Default routing pattern name.                                                |
| `AGLOOM_BANNER`   | Set `0` / `false` to suppress the stderr startup banner.                     |

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
