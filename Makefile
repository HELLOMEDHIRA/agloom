.DEFAULT_GOAL := help
SHELL := /bin/bash

# Paths checked by CI (ruff + pyrefly). Keep in sync with .github/workflows/ci.yml.
PY_PKGS := agloom

# ── Development ──────────────────────────────────────────────────────────────

.PHONY: install
install: ## Install all dependencies (dev + docs + optional extras)
	uv sync --all-extras --group dev

.PHONY: install-dev
install-dev: ## Install dev dependencies (including pytest, ruff, pyrefly)
	uv sync --group dev

# ── Quality ──────────────────────────────────────────────────────────────────

.PHONY: lint
lint: ## Run ruff linter (same scope as CI)
	uv run ruff check $(PY_PKGS)

.PHONY: lint-fix
lint-fix: ## Run ruff linter with auto-fix
	uv run ruff check $(PY_PKGS) --fix

.PHONY: format
format: ## Auto-format code with ruff
	uv run ruff format $(PY_PKGS)

.PHONY: format-check
format-check: ## Check formatting without changing files
	uv run ruff format --check $(PY_PKGS)

.PHONY: typecheck
typecheck: ## Run pyrefly on the Python package (same as CI)
	uv run pyrefly check agloom

.PHONY: pyrefly
pyrefly: typecheck ## Alias for typecheck

.PHONY: check
check: lint format-check typecheck ## Lint, format check, and typecheck (matches CI lint job)

.PHONY: fix
fix: lint-fix format ## Auto-fix lint issues and format code (does not run pyrefly)

# ── Testing ──────────────────────────────────────────────────────────────────

.PHONY: test
test: ## Run pytest suite (no API keys required)
	uv run pytest -q

# ── Build & Publish ──────────────────────────────────────────────────────────

.PHONY: build
build: clean-dist ## Build sdist and wheel
	uv build

.PHONY: publish-test
publish-test: build ## Publish to Test PyPI
	uv publish --publish-url https://test.pypi.org/legacy/

.PHONY: publish
publish: build ## Publish to PyPI (requires UV_PUBLISH_TOKEN)
	uv publish

# ── Docs ─────────────────────────────────────────────────────────────────────

.PHONY: docs-prepare
docs-prepare: ## Copy package docs into docs/_packages/ for MkDocs (no Python script; shell only)
	rm -rf docs/_packages
	mkdir -p docs/_packages
	cp -R agloom/docs docs/_packages/agloom
	cp -R agloom_cli/docs docs/_packages/agloom_cli
	cp -R agloom_web/docs docs/_packages/agloom_web

.PHONY: docs
docs: docs-prepare ## Serve docs locally (http://127.0.0.1:8000)
	uv run mkdocs serve

.PHONY: docs-build
docs-build: docs-prepare ## Build static docs site (strict mode)
	uv run mkdocs build --strict

# ── Cleanup ──────────────────────────────────────────────────────────────────

.PHONY: clean
clean: clean-dist clean-build ## Remove all build artifacts

.PHONY: clean-dist
clean-dist: ## Remove dist/
	rm -rf dist/

.PHONY: clean-build
clean-build: ## Remove build artifacts and caches
	rm -rf build/ *.egg-info .ruff_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# ── Help ─────────────────────────────────────────────────────────────────────

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'
