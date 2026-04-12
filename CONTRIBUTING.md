# Contributing to agloom

Thank you for considering contributing to agloom! This guide will help you get set up and familiar with our development workflow.

## Prerequisites

- Python 3.11 or later
- [uv](https://docs.astral.sh/uv/) package manager
- Git

## Development Setup

1. Clone the repository:

```bash
git clone https://github.com/HELLOMEDHIRA/agloom.git
cd agloom
```

2. Install all dependencies (including dev tools and optional extras):

```bash
uv sync --all-extras
```

3. Install pre-commit hooks:

```bash
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

4. Verify everything works:

```bash
uv run ruff check agloom/
uv run ruff format --check agloom/
uv run pyrefly check agloom/
```

## Running Tests

The test suite uses stdlib `asyncio` and `assert` (no pytest). It requires a `GROQ_API_KEY` environment variable for integration tests with a real LLM:

```bash
export GROQ_API_KEY="your-key-here"  # pragma: allowlist secret
uv run python test.py
```

Tests cover: models, validation, frozen agents, memory, tools, classifier, all 9 patterns, feedback, skills, multi-agent isolation, HITL, streaming, middleware, error handling, and real-user scenarios.

## Code Quality

### Linting (ruff)

```bash
uv run ruff check agloom/          # Check for lint errors
uv run ruff check agloom/ --fix    # Auto-fix what's possible
```

### Formatting (ruff)

```bash
uv run ruff format agloom/          # Format code
uv run ruff format --check agloom/  # Check without changing
```

### Type Checking (pyrefly)

```bash
uv run pyrefly check agloom/
```

### All checks at once (pre-commit)

```bash
uv run pre-commit run --all-files
```

## Commit Conventions

We use [Conventional Commits](https://www.conventionalcommits.org/) enforced by [commitizen](https://commitizen-tools.github.io/commitizen/). The pre-commit hook validates your commit messages automatically.

Format: `<type>(<scope>): <description>`

Types:
- `feat` — new feature
- `fix` — bug fix
- `docs` — documentation only
- `refactor` — code change that neither fixes a bug nor adds a feature
- `perf` — performance improvement
- `test` — adding or correcting tests
- `ci` — CI/CD changes
- `chore` — maintenance tasks

Examples:
```
feat(patterns): add step tracing to REACT handler
fix(memory): prevent session memory overflow beyond max_turns
docs: add streaming examples to README
```

## Pull Request Process

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/your-feature
   ```

2. Make your changes. Ensure:
   - All tests pass (`uv run python test.py`)
   - Linting passes (`uv run ruff check agloom/`)
   - Formatting is correct (`uv run ruff format --check agloom/`)
   - Type checking passes (`uv run pyrefly check agloom/`)

3. Commit with a conventional commit message.

4. Push and open a PR against `main`.

5. Describe your changes clearly in the PR description. Include:
   - What the change does
   - Why it's needed
   - How to test it

## Project Structure

```
agloom/
├── agloom/              # Package source
│   ├── __init__.py         # Public API exports
│   ├── unified_agent.py    # create_agent + UnifiedAgent
│   ├── models.py           # Pydantic models and enums
│   ├── classifier.py       # Query analysis / pattern selection
│   ├── worker.py           # Ephemeral worker execution
│   ├── patterns/           # 9 execution pattern handlers
│   ├── memory/             # Session + long-term memory
│   ├── skills/             # Skill learning, registry, lifecycle
│   ├── feedback/           # Auto-eval, user feedback, trends
│   ├── llm_utils.py        # Robust LLM calls, circuit breaker
│   ├── logging_utils.py    # Structured logging
│   ├── cache.py            # Semantic query cache
│   └── mcp_support.py      # MCP server integration
├── test.py                 # Comprehensive test suite
├── examples/               # Usage examples
├── pyproject.toml          # Project metadata and tool config
└── .github/workflows/      # CI/CD
```

## Questions?

Open an issue on GitHub if you have questions about contributing or need help getting set up.
