# Smart Context & Embeddings

> *How Agloom injects relevant code context for accurate, token-optimized queries.*

---

## Overview

Agloom uses intelligent context injection to provide relevant code without overwhelming the LLM with too much information.

---

## How It Works

### 1. Project Indexing

When you first run Agloom in a project, it builds an index:

```
<project>/.agloom/
├── context_index_abc12345.json   # Serialized project index (per project hash)
```

### 2. Code Chunking

Files are chunked into manageable pieces:

- **Python**: Per function, per class, per method
- **JavaScript**: Per function, per class
- **Other**: By file (~5000 chars)

### 3. Keyword Extraction

Each chunk extracts keywords for fast matching:

```python
def authenticate_user(request):
    # Keywords: authenticate_user, login, credentials
```

---

## Query Processing

When you ask a question:

1. **Extract keywords** from query
2. **Search index** - embeddings + keyword fallback
3. **Select top 3** most relevant chunks
4. **Inject context** into system prompt
5. **Track modified files** for next query

---

## Token Optimization

Only relevant code is injected:

```
Query: "fix login error"
→ Injects: auth.py (login function), views.py (login view)
→ Excludes: templates/, static/, migrations/
```

**Token Budget**: ~2000 tokens for context

---

## Project Rules

Project rules provide best practices:

### Analysis

On first run, Agloom analyzes:

| Property | Detects |
|----------|----------|
| Language | Python, JavaScript, Go, Rust |
| Framework | Django, FastAPI, Express |
| Test framework | pytest, unittest |
| Lint tool | ruff, eslint |

### Generated Rules

```yaml
code_style:
  naming:
    functions: snake_case
    classes: PascalCase

testing:
  framework: pytest
  patterns:
    - test_*.py

validation:
  lint:
    tool: ruff
```

---

## Custom Rules

Provide custom rules via `rules_dir`:

```bash
agloom --rules-dir ./my-rules
```

```yaml
# my-rules/coding.yaml
code_style:
  naming:
    files: snake_case
```

---

## Session Management

Each session stores:

- **Project structure** - file tree
- **File summaries** - function/class counts
- **Modified files** - changes during session

```
<project>/.agloom/sessions/
├── abc12345.json    # Session data
└── messages: [...]
```

---

## Configuration

```yaml
rules:
  dir: "./rules"     # Custom rules directory
  refresh: false    # Auto-refresh on session start
```

---

## Commands

```bash
# Refresh project index
agloom refresh-rules
agloom --refresh-rules
```

---

## See Also

- [CLI Reference](guides/cli.md)
- [Memory System](features/memory.md)