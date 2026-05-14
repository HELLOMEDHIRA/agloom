# Contributing to agloom

Thank you for considering contributing to agloom. This guide covers setup and workflow.

## Prerequisites

- Python 3.12.x only (`requires-python = ">=3.12,<3.13"` in `pyproject.toml`)
- Node.js >=24.15.0 when working on `agloom_cli/` or `agloom_web/` (`npm install` in that package directory — no repo-root Node workspace)
- [uv](https://docs.astral.sh/uv/) package manager
- Git

## Development Setup

1. Clone the repository:

```bash
git clone https://github.com/HELLOMEDHIRA/agloom.git
cd agloom
```

1. Install dependencies (library extras + development tools):

```bash
uv sync --all-extras --group dev
```

1. Install pre-commit hooks:

```bash
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

1. Verify locally:

```bash
uv run ruff check agloom
uv run ruff format --check agloom
uv run pyrefly check agloom
uv run pytest -q
```

## Running Tests

Tests live under `agloom/tests/` and use **pytest** (with **pytest-asyncio** for async cases). Most tests do not require API keys or network access.

```bash
uv run pytest
```

## Code Quality

### Linting (ruff)

```bash
uv run ruff check agloom
uv run ruff check agloom --fix
```

### Formatting (ruff)

```bash
uv run ruff format agloom
uv run ruff format --check agloom
```

### Type Checking (pyrefly)

Pyrefly type-checks the `agloom` Python package; TypeScript projects under `agloom_cli/` and `agloom_web/` use ESLint + `tsc`.

```bash
uv run pyrefly check agloom
```

### agloom CLI and web (`agloom_cli/`, `agloom_web/`)

Each folder is its own npm package: run **install and scripts inside that directory** (there is no repo-root `package.json`).

```bash
cd agloom_cli && npm install && npm run build && npm test
cd agloom_web && npm install && npm run build && npm test
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

```text
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

   - Tests pass: `uv run pytest`
   - Lint: `uv run ruff check agloom`
   - Format: `uv run ruff format --check agloom`
   - Types: `uv run pyrefly check agloom`
   - If you changed `agloom_cli/` or `agloom_web/`: `npm install`, `npm run build`, and `npm test` in that folder

3. Commit with a conventional commit message.

4. Push and open a PR against `main`.

5. Describe what changed, why, and how reviewers can verify.

## Project Structure

```text
agloom/
├── agloom/              # Core library (`agloom/tests/`, `agloom/examples/`, `agloom/docs/`)
├── agloom_cli/          # agloom CLI — terminal client, npm package ``agloom-cli`` (`agloom_cli/docs/`)
├── agloom_web/          # Vite workspace (`agloom_web/docs/`)
├── docs/                # MkDocs root: `index.md`, `contributing.md`, `requirements.txt`; `docs/_packages/` is copied before build
├── pyproject.toml       # Metadata and tool configuration
└── .github/workflows/   # CI/CD
```

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting and tooling risk notes.

## agloom-cli: AGP bridge (maintainers)

The terminal client (`agloom_cli/`, npm package **`agloom-cli`**) spawns **`agloom-runtime serve --transport=stdio`** and parses AGP on stdout. Use this section when changing protocol handling or UI wiring.

### Layout

| Area                         | Role                                                                                                         |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `src/runtime/bridge.ts`      | `createAGPBridge()` — spawns `agloom-runtime`, parses NDJSON, typed `on`/`emit` via internal `EventEmitter`. |
| `src/store/session.ts`       | Single zustand reducer: **`dispatch(AGPEvent)`** updates UI state + **Wire notes**.                          |
| `src/hooks/useAGPStream.tsx` | Subscribes the bridge to the store (strict-mode safe).                                                       |
| `src/components/*`           | Interactive TUI (React); slash commands are handled in `App.tsx`.                                                             |

### Adding a new inbound event type

1. Mirror the Python model in **`src/types/agp.ts`** (and keep **`agloom_web`** copy identical).
2. Handle it in **`session.ts`** → `dispatch` switch (update structured state and/or **`protocolNotes`**).
3. Add a **jest** case in **`src/__tests__/store.test.ts`** for the reducer branch.

### Tests (`agloom_cli/`)

- **`npm test`** — `bridge.test.ts` (serialization, NDJSON framing) + `store.test.ts` (reducers).
- TUI components are not rendered in CI; exercise logic via the store where possible.

### Build (`agloom_cli/`)

```bash
npm run build    # tsc → dist/
npm run lint
npm run typecheck
```

The bridge is a **factory** (`createAGPBridge`) wrapping Node’s `EventEmitter`; the public type is **`AGPBridge`** (typed `on` / `once` / `off` / `emit`).

User-facing AGP stdio rules (stdout vs stderr) are documented in **`agloom_cli/docs/reference.md`** (published under MkDocs).

## Questions?

Open an issue on GitHub if you need help with setup or contribution workflow.
