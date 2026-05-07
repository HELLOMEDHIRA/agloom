# Agloom CLI — The AI Programming Assistant Shell

> *The intelligent CLI for professional AI-assisted development — with project awareness, smart context injection, and auto-learned best practices.*

---

## Why Agloom CLI?

Modern agent frameworks require you to make dozens of architectural decisions before writing your first line of code. Which execution pattern? How to handle memory? What about skills? MCP integration? The complexity is overwhelming.

**Agloom CLI solves this by providing a single interface that handles all of it — automatically.**

---

## The Problems We Solve

### 1. Pattern Selection is Guesswork

Most agent frameworks force you to choose an execution pattern upfront: REACT? SUPERVISOR? PIPELINE? But the right pattern depends on your query — its complexity, parallelizability, tool requirements.

**Our solution:** Agloom auto-classifies every query using a 9-dimension analysis:

```
User: "Research quantum computing and write a Python implementation"

Classification:
  - Complexity: 7/10 (multi-step)
  - Parallelizable: Yes (research can parallelize)
  - Requires reasoning: Yes
  - Tool-heavy: Yes
  - Has subtasks: Yes

→ Pattern: SUPERVISOR
  → Decomposes into: [Research subtask, Implementation subtask]
  → Executes in parallel
  → Synthesizes final response
```

You just ask. Agloom figures out the rest.

### 2. Tool Management is Tedious

Every other CLI requires manual tool registration — import each file, configure each tool, maintain a registry.

**Our solution:** Auto-discovery from directory:

```bash
agloom --tools ./my-tools
```

- Scans directory for `.py` files
- Auto-detects `@tool` decorated functions
- Converts type-annotated functions to tools
- Registers all in one pass

### 3. Memory Doesn't Persist Across Sessions

Most CLI agents start fresh every time — they forget your project conventions, your coding style, your preferences.

**Our solution:** Multi-layer memory:

```
Session Memory       → Current conversation
Long-Term Store      → Persistent across runs (Qdrant-backed)
Passive Injection    → Skill context + delegation context
```

### 4. Agents Don't Improve Over Time

Run the same task twice, get the same result — even if the first attempt failed. No learning, no skill formation.

**Our solution:** Self-learning skills system:

```bash
agloom "build a REST API in FastAPI"

# Agent uses: read_file → write_file → run_shell → test
# After completion:
# → Analyzes: which tools + approach worked
# → Creates: skill template with instructions
# → Next time: loads skill → 10x faster execution
```

---

## Cost-Optimized Execution

### Auto-Selection Saves API Costs

```
Query: "List files and count lines"

❌ OTHER CLIS:
   → Forces REACT pattern
   → 15 LLM calls (each tool call = API call)
   → $0.60 in LLM costs

✓ AGLOOM CLI:
   → Auto-classifies as simple (complexity: 2)
   → Selects DIRECT pattern
   → 1 LLM call
   → $0.04 in LLM costs
```

**15x cost reduction** for simple queries.

### Parallel Execution for Complex Tasks

```
Query: "Analyze sales, marketing, and engineering metrics"

❌ OTHER CLIS:
   → Sequential execution
   → 3 tasks × 5 min = 15 min total
   → Expensive LLM time

✓ AGLOOM CLI:
   → Auto-detects parallelizable
   → SUPERVISOR pattern
   → 3 workers in parallel
   → 5 min total
   → 66% time savings
```

### Smart Caching

- Query cache for repeated requests
- Token-level rate limiting
- Circuit breakers prevent cascade failures

---

## Fast Execution Pipeline

### 1. Query Analysis (Cached)

```
First time:  ~500ms
Cached:      ~10ms (subsequent same query)
```

### 2. Pattern Selection (Always Fast)

```
Complexity analysis → <50ms
No LLM call required
```

### 3. Tool Selection (Lazy Loading)

```
Load tools on first use
Reuse across sessions
```

### 4. Memory Context (Optimized)

```
Passive injection only what's relevant
Semantic search <100ms
```

---

## Rich Terminal UI

```
╭────────────────────────────────────╮
│   _   ___ _    ___   ___  __  __  │
│  /_\ / __| |  / _ \ / _ \|  \/  | │
│ / _ \ (_ | |_| (_) | (_) | |\/| | │
│/_/ \_\___|____\___/ \___/|_|  |_| │
╰─────────────────────────── v0.1.0 ─╯

╭─ STATUS ──────────────────────────────────────────────────╮
│ ✓ LangSmith: enabled (agloom-cli)                        │
│ Thread: dc16a756                                         │
│ ✓ Loaded 44 tool(s)                                      │
│ ✓ Ready to code!                                         │
╰───────────────────────────────────────────────────────────╯

❯ Analyze this codebase for security vulnerabilities
```

Features:
- Real-time token streaming
- Tool call visualization (`🔧 read_file` → `✓ output`)
- Worker status indicators
- Thinking indicator with spinner
- Conversation history

---

## Built-in Tools (46 Ready)

| Category | Tools |
|----------|-------|
| **File System** | read_file, write_file, list_directory, search_files, create_directory, remove_file, copy_file, move_file, get_file_info, file_exists |
| **Shell** | run_shell, run_shell_interactive, get_system_info, get_env_var, set_env_var, list_env_vars |
| **HTTP** | http_request, http_get, http_post, http_put, http_delete, http_head, fetch_json |
| **Web Search** | web_search, search_web, find_docs, search_github (Tavily API) |
| **Task Planning** | create_task_plan, get_current_task, complete_step, update_task_progress, show_remaining_steps, clear_task_tracker |
| **Path Operations** | get_working_directory, set_working_directory, push_working_directory, pop_working_directory, path_join, path_parent, path_absolute, path_exists, path_is_file, path_is_directory, path_basename, path_extension, path_stem |

---

## Production Features

### Human-in-the-Loop (HITL)

```bash
agloom --require-approval
# or bypass config for one run:
agloom --no-require-approval
```

Prompts for confirmation before:
- Shell command execution
- File write/delete
- Directory changes
- HTTP requests

### Reliability

- **Timeouts**: LLM (120s), classifier (30s), configurable
- **Retries**: Max retries with exponential backoff
- **Rate Limiting**: Token-level rate control
- **Circuit Breakers**: Prevents cascade failures

### Observability

Auto-detected LangSmith integration:

```bash
export LANGCHAIN_TRACING_V2=true
agloom
```

---

## Configuration

YAML or TOML:

```yaml
# agloom.yaml

# Model
ai:
  model: gpt-4o
  name: my-agent
  system_prompt: "You are a Python expert"

# Memory & Skills
memory:
  enabled: true
  max_turns: 50

skills:
  enabled: true
  max_skills: 30

# Auto-summarize (top-level, not under memory)
auto_summarize: true
summarize_threshold: 200000

# Tools
tools:
  dir: ./tools

# MCP
mcp:
  servers: ""

# Safety
safety:
  require_approval: true
  auto_approve: "read_file,list_directory,get_working_directory,initialize_project,bootstrap_progress,save_progress,get_next_task,update_task,add_task,git_status,git_log,git_commit,git_checkpoint,git_revert_hint,load_skill"
  allowlist_strict_tools: true

# Execution
execution:
  max_concurrent: 4
  max_retries: 2
  retry_delay: 1.0
  llm_timeout: 120.0
  classifier_timeout: 30.0

# Rules
rules:
  dir: ""
  refresh: false
```

Config precedence: CLI → config file → env vars → defaults

---

## Usage

### Quick Start

```bash
# Interactive shell
agloom

# Single prompt
agloom "What is quantum computing?"

# Specific model
agloom -m gpt-4o
```

### With Tools

```bash
# Auto-discover
agloom --tools ./my-tools
```

### With Memory

```bash
# Persistent memory
agloom --memory-path ./memory.db

# Enable skills
agloom --skills --max-skills 50
```

### With Safety

```bash
# Require approval
agloom --require-approval

# Auto-approve safe tools
agloom --require-approval --auto-approve read_file,list_directory
```

---

## Getting Started

```bash
# Install
pip install agloom

# Run
agloom
```

No configuration required. 46 tools ready. 9 patterns available. Memory enabled by default.

---

## See Also

- [Execution Patterns](../concepts/patterns.md) — All 9 patterns explained
- [Memory System](../features/memory.md) — Deep dive on memory architecture
- [Skill Learning](../features/skills.md) — How agents learn from interaction
- [HITL](../features/hitl.md) — 4 levels of human interruption
- [MCP](../features/mcp.md) — Model Context Protocol support