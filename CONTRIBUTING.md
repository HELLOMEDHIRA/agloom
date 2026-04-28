# Contributing to agloom

Thank you for considering contributing to agloom. This guide covers setup and workflow.

## Prerequisites

- Python 3.12.x (required by the bundled `agsuperbrain` CLI dependency)
- [uv](https://docs.astral.sh/uv/) package manager
- Git

## Development Setup

1. Clone the repository:

```bash
git clone https://github.com/HELLOMEDHIRA/agloom.git
cd agloom
```

2. Install dependencies (library extras + development tools):

```bash
uv sync --all-extras --group dev
```

3. Install pre-commit hooks:

```bash
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

4. Verify locally:

```bash
uv run ruff check agloom agloom_cli tests
uv run ruff format --check agloom agloom_cli tests
uv run pyrefly check agloom agloom_cli examples tests
uv run pytest tests -q
```

## Running Tests

Tests live under `tests/` and use **pytest** (with **pytest-asyncio** for async cases). They do not require API keys or network access.

```bash
uv run pytest tests
```

## Code Quality

### Linting (ruff)

```bash
uv run ruff check agloom agloom_cli tests
uv run ruff check agloom agloom_cli tests --fix
```

### Formatting (ruff)

```bash
uv run ruff format agloom agloom_cli tests
uv run ruff format --check agloom agloom_cli tests
```

### Type Checking (pyrefly)

Pyrefly targets the published packages (`agloom`, `agloom_cli`). The `tests/` tree is linted with ruff and executed with pytest.

```bash
uv run pyrefly check agloom agloom_cli examples tests
```

### Pre-commit (all hooks)

```bash
uv run pre-commit run --all-files
```

## Commit Conventions

We use [Conventional Commits](https://www.conventionalcommits.org/) via [commitizen](https://commitizen-tools.github.io/commitizen/). The commit-msg hook validates messages.

Format: `<type>(<scope>): <description>`

Types:

- `feat` — new feature
- `fix` — bug fix
- `docs` — documentation only
- `refactor` — change that neither fixes a bug nor adds a feature
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

2. Before opening a PR, ensure:

   - Tests pass: `uv run pytest tests`
   - Lint: `uv run ruff check agloom agloom_cli tests`
   - Format: `uv run ruff format --check agloom agloom_cli tests`
   - Types: `uv run pyrefly check agloom agloom_cli examples tests`

3. Commit with a conventional commit message.

4. Push and open a PR against `main`.

5. Describe what changed, why, and how reviewers can verify.

## Project Structure

```
agloom/
├── agloom/              # Core library
├── agloom_cli/          # CLI package (`agloom` command)
├── tests/               # Pytest suite
├── examples/            # Usage examples
├── docs/                # MkDocs sources
├── pyproject.toml       # Metadata and tool configuration
└── .github/workflows/   # CI/CD
```

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting and tooling risk notes.

## Questions?

Open an issue on GitHub if you need help with setup or contribution workflow.
