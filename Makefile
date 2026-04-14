.DEFAULT_GOAL := help
SHELL := /bin/bash

# ── Development ──────────────────────────────────────────────────────────────

.PHONY: install
install: ## Install all dependencies (dev + docs)
	uv sync --all-extras

.PHONY: install-dev
install-dev: ## Install dev dependencies only
	uv sync

# ── Quality ──────────────────────────────────────────────────────────────────

.PHONY: lint
lint: ## Run ruff linter
	ruff check .

.PHONY: lint-fix
lint-fix: ## Run ruff linter with auto-fix
	ruff check . --fix

.PHONY: format
format: ## Auto-format code with ruff
	ruff format .

.PHONY: format-check
format-check: ## Check formatting without changing files
	ruff format --check .

.PHONY: check
check: lint format-check ## Run all quality checks (lint + format)

.PHONY: fix
fix: lint-fix format ## Auto-fix lint issues and format code

# ── Testing ──────────────────────────────────────────────────────────────────

.PHONY: test
test: ## Run full test suite (requires GROQ_API_KEY)
	python test.py

.PHONY: test-unit
test-unit: ## Run unit tests only (no API key needed)
	python -c "from test import *; sec1_models_and_enums(); sec2_agent_config(); sec3_frozen_validation(); sec4_memory(); sec5_helpers(); sec6_skills_models(); sec7_feedback(); sec8_tools(); print('\nUnit tests done.')"

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

.PHONY: docs
docs: ## Serve docs locally (http://127.0.0.1:8000)
	mkdocs serve

.PHONY: docs-build
docs-build: ## Build static docs site
	mkdocs build

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
