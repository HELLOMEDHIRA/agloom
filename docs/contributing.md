# Contributing

## Documentation layout

Source Markdown for the MkDocs site lives **with each package**: `agloom/docs/`, `agloom_cli/docs/`, `agloom_web/docs/`. Repo-root `docs/` holds only the landing page, this file, and build requirements.

Before `mkdocs serve` or `mkdocs build`, run **`make docs-prepare`** so those trees are copied into `docs/_packages/` (ignored by git). Read the Docs runs the same copy step in CI.

---

See the [Contributing Guide](https://github.com/HELLOMEDHIRA/agloom/blob/main/CONTRIBUTING.md) for:

- Development setup (Python 3.12.x only, Node.js ≥24.15.0 for `agloom_cli` / `agloom_web`, uv)
- Running tests (`uv run pytest`)
- Linting and formatting (`ruff` on `agloom`; ESLint on `agloom_cli` / `agloom_web`)
- Type checking (`pyrefly`)
- Commit conventions (Conventional Commits)
- Pull request process
