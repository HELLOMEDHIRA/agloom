# CLI Shell — Quick Start

> Get started with agloom CLI in 30 seconds.

## What is Agloom CLI?

A production-ready terminal-based AI programming assistant. Not just for agents — build, test, debug, and ship software:

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
pip install agloom[all]
```

## Quick Start

```bash
# Start interactive shell (first run auto-creates config)
agloom
```

```
$ agloom
[agloom] Config created at ~/.agloom/agloom.yaml
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

## Single Prompt Mode

```bash
# Run a single query and exit
agloom "What is 2+2?"

# With specific model
agloom -m groq "Explain quantum computing in 2 sentences"
agloom -m llama-3.1-70b-versatile "Hello"
```

## Configuration

### Auto-created Config

On first run, agloom creates `~/.agloom/agloom.yaml`:

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

skills:
  enabled: true
  max_skills: 30

rules:
  dir: ""
  refresh: false

execution:
  max_concurrent: 4
  max_retries: 2
  llm_timeout: 120.0

safety:
  require_approval: false
  auto_approve: "read_file,list_directory"
```

### Project Override

Create `.agloom.yaml` in your project to override defaults:

```yaml
ai:
  model: groq

tools:
  dir: ./my-tools

rules:
  dir: ./my-rules
  refresh: false
```

### Custom Rules Directory

Place YAML files in a custom directory:

```bash
# my-rules/coding-style.yaml
code_style:
  naming:
    functions: snake_case
    classes: PascalCase

# my-rules/testing.yaml
testing:
  framework: pytest
  patterns:
    - test_*.py
```

```bash
agloom --rules-dir ./my-rules
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
- **Embeddings**: OpenAI ada + keyword fallback
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

Agloom manages multiple project sessions:

```bash
# List all sessions
agloom sessions

# List all projects
agloom projects

# Switch to a different session
agloom session-switch abc12345

# Create new session with specific project
agloom --session new --project /path/to/project
```

Each session keeps:
- Conversation history
- Project structure + file summaries
- Modified files tracking
- Turn count

## Common Options

| Option | Description |
|-------|-------------|
| `-m, --model` | Model ID (default: auto) |
| `-c, --config` | Config file path |
| `-t, --tools` | Tools directory |
| `-p, --project` | Project directory |
| `-s, --session` | Session ID |
| `--rules-dir` | Custom rules directory |
| `--refresh-rules` | Force refresh rules |
| `-v, --verbose` | Enable verbose logging |
| `--memory/--no-memory` | Enable/disable memory |
| `--skills/--no-skills` | Enable/disable skills |
| `--require-approval` | Require approval for shell/file operations |

## Built-in Tools (46)

| Category | Tools |
|----------|-------|
| **File** | read_file, write_file, list_directory, search_files, create_directory, remove_file, copy_file, move_file, get_file_info, file_exists |
| **Shell** | run_shell, run_shell_interactive, get_system_info |
| **HTTP** | http_get, http_post, http_put, http_delete, http_request |
| **Web** | web_search, search_web, find_docs, search_github |
| **Task** | create_task_plan, get_current_task, complete_step |
| **Path** | get_working_directory, set_working_directory, path_join, path_parent |

## Data Storage

Agloom stores data in `~/.agloom/`:

```
~/.agloom/
├── agloom.yaml           # User config
├── sessions/
│   ├── abc12345.json    # Session data
│   └── xyz789.json
├── indexes/             # Embeddings cache
├── rules/               # Project rules cache
├── skills/              # Learned skills
└── logs/
```

## What's Next?

| Topic | Link |
|-------|------|
| Full CLI Reference | [CLI Reference](../guides/cli.md) |
| Execution Patterns | [Patterns](../concepts/patterns.md) |
| Adding Custom Tools | [Tools](../features/tools.md) |
| Memory System | [Memory](../features/memory.md) |