# CLI Shell — Quick Start

> Get started with agloom CLI in 30 seconds.

## What is Agloom CLI?

A production-ready terminal-based AI programming assistant. Build, test, debug, and ship software:

- **Code assistance** - Write, review, debug, refactor code
- **Shell commands** - Execute terminal commands
- **File operations** - Read, write, search files
- **Web research** - Search docs, find bugs, solutions
- **Task automation** - Break down complex tasks
- **Persistent memory** - Remembers your project context
- **Smart context** - Embeddings + keyword-based file search
- **Project rules** - Auto-analyzed best practices

## Install

```bash
pip install agloom
```

## Super-Brain (built in)

The CLI always uses [Super-Brain](https://agsuperbrain.readthedocs.io/en/latest/): on each start it runs **`agsuperbrain init`** in the detected project directory and connects the **Super-Brain MCP** server (local graph + tools). It ships with `agloom` (`agsuperbrain` dependency). Override the stdio command in `<project>/.agloom/agloom.yaml` under `mcp.superbrain` if needed.

## Quick Start

```bash
# Start interactive shell (first run auto-creates config)
agloom
```

```
$ agloom
[agloom] Config created at <project>/.agloom/agloom.yaml
[agloom] Session: abc12345
[agloom] Added to .gitignore

agloom shell — type 'exit' to quit
Model: auto
Tools: 46
Memory: enabled

Project: /workspace/my-app
Language: python (django)
Type: webapp
Git: main dirty

> What causes auroras?
[1/1] Calling web_search...
Auroras are caused by charged particles from the sun...
> exit
```

**Interactive shell:** the **Thinking** pane is the live **agent event** stream (classify, tools, steps, …) from the runtime — not Python `logging` INFO lines. **Framework** chatter (`httpx`, Groq SDK, `aiosqlite`, LangGraph store, …) stays **off the console** below WARNING even with **`--verbose`**, so the layout stays readable. Default mode also hides **`agloom.*`** INFO/DEBUG; **`--verbose`** turns on **agloom** package debug logging only. After each reply you get a compact **Thinking** summary unless **`thinking on`**, **`thinking off`**, **`thinking`** (toggle), or **`AGLOOM_EXPAND_THINKING=1`** says otherwise.

## Single Prompt Mode

```bash
# Run a single query and exit
agloom "What is 2+2?"

# Default: ``ai.model`` in ``.agloom/agloom.yaml``, then provider auto-detect (no ``-m``).
# Per-run override (model id for your installed provider, e.g. Groq):
agloom -m gpt-4o "Explain quantum computing in 2 sentences"
agloom -m llama-3.3-70b-versatile "Hello"
```

## Configuration

### Auto-created Config

On first run, agloom creates `<project>/.agloom/agloom.yaml` (under the detected project root):

```yaml
ai:
  name: agloom
  model: auto
  system_prompt: |
    You are an autonomous AI programming assistant...

mcp:
  servers: ""

tools:
  dir: ""
  disabled: []

memory:
  enabled: true
  max_turns: 50

auto_summarize: true
summarize_threshold: 200000

skills:
  enabled: true
  max_skills: 30

rules:
  dir: ""
  refresh: false

execution:
  max_concurrent: 4
  max_retries: 2
  retry_delay: 1.0
  llm_timeout: 120.0
  classifier_timeout: 30.0

safety:
  require_approval: false
  auto_approve: "read_file,list_directory,get_working_directory"

session:
  current_session: ""
  last_updated: ""
```

### CLI Options

| Option | Alias | Description | Default |
|--------|-------|-------------|---------|
| `--model` | `-m` | Model ID (e.g. `llama-3.3-70b-versatile`, `gpt-4o`). Overrides `ai.model` in `.agloom/agloom.yaml`. | from config, then auto-detect |
| `--name` | | Agent name | agloom |
| `--system-prompt` | | Custom system prompt | (default) |
| `--tools` | `-t` | Custom tools directory | |
| `--memory/--no-memory` | | Enable/disable memory | (config default) |
| `--memory-path` | | Memory storage path | auto |
| `--skills/--no-skills` | | Enable/disable skills | (config default) |
| `--max-skills` | | Max skills to learn | 30 |
| `--max-turns` | | Max session turns | 50 |
| `--auto-summarize/--no-summarize` | | Auto-summarize conversations | (config default) |
| `--summarize-threshold` | | Token threshold for summarize | 200000 |
| `--mcp` | | MCP servers (comma-separated) | |
| `--interrupt-before` | | Interrupt before patterns | |
| `--interrupt-after` | | Interrupt after patterns | |
| `--interrupt-before-tools` | | Interrupt before specific tools | |
| `--require-approval` | | Require approval for shell/file ops | disabled |
| `--auto-approve` | | Tools to auto-approve | |
| `--max-concurrent` | | Max concurrent workers | 4 |
| `--max-retries` | | Max retries | 2 |
| `--retry-delay` | | Retry delay (seconds) | 1.0 |
| `--llm-timeout` | | LLM timeout (seconds) | 120.0 |
| `--classifier-timeout` | | Classifier timeout | 30.0 |
| `--fallback-pattern` | | Fallback pattern | |
| `--frozen` | | Enable frozen mode | disabled |
| `--frozen-template` | | Frozen template | |
| `--feedback-webhook` | | Feedback webhook URL | |
| `--cache-dir` | | Cache directory | |
| `--config` | `-c` | Config file path | |
| `--session` | `-s` | Session / thread ID (32-char hex, hyphenated UUID, or safe alnum/`_`/`-`) | |
| `--strict-session` | | With `--session`: exit with error if `sessions/<id>.json` does not exist | disabled |
| `--project` | `-p` | Project directory | auto-detect |
| `--rules-dir` | | Custom rules directory | |
| `--refresh-rules` | | Force refresh rules | disabled |
| `--verbose` | `-v` | Verbose logging | disabled |
| `--no-builtins` | | Disable built-in tools | disabled |
| `--version` | | Show version | |

### Project Override

Create `.agloom.yaml` in your project to override defaults:

```yaml
ai:
  model: llama-3.3-70b-versatile

tools:
  dir: ./my-tools

rules:
  dir: ./my-rules
  refresh: false
```

### Environment Variables

```bash
export OPENAI_API_KEY="sk-..."
export GROQ_API_KEY="gsk_..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Project Context Awareness

Agloom automatically detects your project:

```bash
# Auto-detected on shell start
agloom

# Or specify project directory
agloom --project /path/to/project
```

It detects:
- **Language**: Python, JavaScript, TypeScript, Go, Rust, etc.
- **Frameworks**: Django, Flask, FastAPI, Express, Next.js, etc.
- **Project type**: library, api, webapp, cli
- **Git info**: branch, dirty/clean status
- **Test framework**: pytest, unittest
- **Linting**: ruff, eslint, mypy

## Smart Context Injection

Agloom uses embeddings + keyword matching for accurate code context:

```bash
# On query, relevant code is injected automatically
# "fix the login view" → injects auth.py, views.py (login function)
```

Features:
- **Embeddings**: BGE (local, free, no API key) + keyword fallback
- **Chunking**: Per-function, per-class
- **Token optimization**: Only relevant code injected

## Project Rules

Agloom analyzes your project and generates rules:

```bash
# Refresh rules manually
agloom refresh-rules
agloom --refresh-rules
```

Rules include:
- Code style (naming conventions)
- Testing patterns
- Validation (lint, type checking)
- Git workflow
- Debugging guidelines

## Multi-Session Management

Agloom manages multiple project sessions from the main CLI (no separate subcommands):

```bash
# Resume or pin a session / project (examples)
agloom --session <session_id> --project /path/to/project

# Fail fast if you mistyped the id (no session JSON under .agloom/sessions/)
agloom --session <session_id> --strict-session --project /path/to/project
```

**Default:** each `agloom` run starts a **new** thread id (fresh chat). **`--session` / `-s`** is how you **resume** a previous thread (checkpoints, session memory, and `sessions/<id>.json` messages).

Session IDs are validated (no path characters). Hyphenated UUIDs are normalized to the same 32-character hex form used for filenames. If you pass `--session` and there is no `sessions/<id>.json` yet, the CLI warns and continues (new session file); use `--strict-session` to abort instead. `agloom.yaml`’s `session.current_session` is updated **only** when you pass **`--session`**.

Each session keeps:
- Conversation history
- Project structure + file summaries
- Modified files tracking
- Turn count

With **memory enabled**, the CLI also persists LangGraph checkpoints and store data under `.agloom/` (`checkpoints.sqlite`, `graph_store.sqlite`) so the same **`--session`** thread id survives process restarts. `create_agent` itself is unchanged; only the CLI passes a durable checkpointer and store.

## Data Storage

The CLI stores config and caches in **`<project>/.agloom/`** (next to your repo), not under your home directory:

```
<project>/.agloom/
├── agloom.yaml           # Config for this project
├── sessions/
│   ├── abc12345.json    # Session data (+ optional ``last_run`` audit: config hashes, CLI flags, resolved model)
│   └── xyz789.json
├── checkpoints.sqlite   # LangGraph checkpoints (memory on — session resume)
├── graph_store.sqlite   # LangGraph store (memory on — namespaces / session memory)
├── context_index_*.json # Smart-context index (when built)
├── rules/               # Project rules cache
└── skills/              # SKILL.md trees (learned + optional static)
```

Optional: a `.agloom.yaml` in the project root is merged on top of `agloom.yaml`. If you import `agloom_cli` from Python without the CLI, the library may create `~/.agloom/` with the same layout as a fallback.

## Built-in Tools (46)

| Category | Tools |
|----------|-------|
| **File** | read_file, write_file, list_directory, search_files, create_directory, remove_file, copy_file, move_file, get_file_info, file_exists |
| **Shell** | run_shell, run_shell_interactive, get_system_info, get_env_var, set_env_var, list_env_vars |
| **HTTP** | http_get, http_post, http_put, http_delete, http_head, http_request, fetch_json |
| **Web** | web_search, search_web, find_docs, search_github |
| **Task** | create_task_plan, get_current_task, complete_step, update_task_progress, show_remaining_steps, clear_task_tracker |
| **Path** | get_working_directory, set_working_directory, push_working_directory, pop_working_directory, path_join, path_parent, path_absolute, path_exists, path_is_file, path_is_directory, path_basename, path_extension, path_stem |

## What's Next?

| Topic | Link |
|-------|------|
| Full CLI Reference | [CLI Reference](../guides/cli.md) |
| Smart Context | [Smart Context](../guides/smart-context.md) |
| Execution Patterns | [Patterns](../concepts/patterns.md) |
| Adding Custom Tools | [Tools](../features/tools.md) |
| Memory System | [Memory](../features/memory.md) |