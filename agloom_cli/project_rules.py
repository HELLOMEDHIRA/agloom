"""Project rules management with analysis and smart injection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .config import HomeDir

DEFAULT_RULES = """
# Default rules - always available if no project rules

code_style:
  naming:
    files: snake_case
    classes: PascalCase
    functions: snake_case
    constants: SCREAMING_SNAKE_CASE

  formatting:
    indent: 4 spaces
    max_line_length: 100
    trailing_comma: true

  imports:
    order: stdlib, third_party, local
    wildcard: false

testing:
  framework: pytest
  patterns:
    - test_*.py
    - *_test.py
  fixtures: fixtures/
  coverage_min: 80

validation:
  lint:
    tool: ruff
    rules: E, F, W
  typecheck: mypy
  format: black

git:
  commits:
    format: "type(scope): description"
    types: [feat, fix, docs, style, refactor, test, chore]
  branch: main
  protected: [main, develop]

debugging:
  logging: use logging module
  errors: explicit error messages
  traces: include context

documentation:
  docstrings: google style
  readme: true
"""


class ProjectRules:
    """Project-specific rules with analysis."""

    def __init__(
        self,
        project_path: Path,
        rules: dict[str, Any] | None = None,
        analysis: dict[str, Any] | None = None,
        source_file: str | None = None,
    ):
        self.project_path = project_path
        self.project_hash = hashlib.md5(str(project_path.resolve()).encode(), usedforsecurity=False).hexdigest()[:8]
        self.rules = rules or {}
        self.analysis = analysis or {}
        self.source_file = source_file
        self._cached_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_path": str(self.project_path),
            "project_hash": self.project_hash,
            "rules": self.rules,
            "analysis": self.analysis,
            "source_file": self.source_file,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProjectRules:
        return cls(
            project_path=Path(data["project_path"]),
            rules=data.get("rules", {}),
            analysis=data.get("analysis", {}),
            source_file=data.get("source_file"),
        )

    def get_text(self) -> str:
        """Get rules as formatted text for system prompt."""
        if self._cached_text:
            return self._cached_text

        parts = ["# Project Rules\n"]

        # Code style
        if self.rules.get("code_style"):
            cs = self.rules["code_style"]
            parts.append("## Code Style\n")
            if cs.get("naming"):
                parts.append("Naming:")
                for k, v in cs["naming"].items():
                    parts.append(f"  {k}: {v}")
            if cs.get("formatting"):
                parts.append("Formatting:")
                for k, v in cs["formatting"].items():
                    parts.append(f"  {k}: {v}")

        # Testing
        if self.rules.get("testing"):
            t = self.rules["testing"]
            parts.append("\n## Testing\n")
            parts.append(f"Framework: {t.get('framework', 'pytest')}")
            if t.get("patterns"):
                parts.append(f"Patterns: {', '.join(t['patterns'])}")

        # Validation
        if self.rules.get("validation"):
            v = self.rules["validation"]
            parts.append("\n## Validation\n")
            if v.get("lint"):
                parts.append(f"Lint: {v['lint'].get('tool', 'ruff')}")

        # Git
        if self.rules.get("git"):
            g = self.rules["git"]
            parts.append("\n## Git\n")
            if g.get("commits", {}).get("format"):
                parts.append(f"Commit format: {g['commits']['format']}")

        # Debugging
        if self.rules.get("debugging"):
            d = self.rules["debugging"]
            parts.append("\n## Debugging\n")
            parts.append(f"Logging: {d.get('logging', 'logging module')}")

        self._cached_text = "\n".join(parts)
        return self._cached_text

    def save(self, home_dir: Path | None = None) -> None:
        """Save rules to disk."""
        home_dir = home_dir or HomeDir
        rules_dir = home_dir / "rules"
        rules_dir.mkdir(exist_ok=True)

        rules_file = rules_dir / f"{self.project_hash}.json"

        with open(rules_file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, project_path: Path, home_dir: Path | None = None) -> ProjectRules | None:
        """Load rules from disk if exists."""
        home_dir = home_dir or HomeDir
        project_hash = hashlib.md5(str(project_path.resolve()).encode(), usedforsecurity=False).hexdigest()[:8]
        rules_dir = home_dir / "rules"
        rules_file = rules_dir / f"{project_hash}.json"

        if not rules_file.exists():
            return None

        with open(rules_file, encoding="utf-8") as f:
            data = json.load(f)

        return cls.from_dict(data)

    def get_relevant_rules(self, query: str) -> str:
        """Get only rules relevant to the query."""
        query_lower = query.lower()

        # Map keywords to rule sections
        keyword_map = {
            "test": ["testing", "validation"],
            "validate": ["validation"],
            "lint": ["validation"],
            "format": ["code_style", "formatting"],
            "naming": ["code_style", "naming"],
            "commit": ["git", "commits"],
            "branch": ["git", "branch"],
            "log": ["debugging", "logging"],
            "error": ["debugging", "errors"],
            "doc": ["documentation"],
        }

        sections = set()
        for keyword, rule_keys in keyword_map.items():
            if keyword in query_lower:
                sections.update(rule_keys)

        if not sections:
            return self.get_text()

        parts = ["# Relevant Project Rules\n"]
        for section in sections:
            if "." in section:
                # Nested key
                parts_section, key = section.split(".", 1)
                if self.rules.get(parts_section) and self.rules[parts_section].get(key):
                    parts.append(f"\n## {parts_section}.{key}\n")
                    parts.append(str(self.rules[parts_section][key]))
            else:
                if self.rules.get(section):
                    parts.append(f"\n## {section}\n")
                    parts.append(str(self.rules[section]))

        return "".join(parts)


def analyze_project(project_path: Path) -> dict[str, Any]:
    """Full analysis of project for best practices."""
    analysis = {
        "language": None,
        "framework": None,
        "test_framework": None,
        "lint_tools": [],
        "type_checker": None,
        "package_manager": None,
        "has_readme": False,
        "has_docker": False,
        "git_workflow": None,
        "ci_cd": None,
    }

    # Check key files
    files = list(project_path.iterdir())
    file_names = {f.name for f in files if f.is_file()}

    # Language detection
    if "pyproject.toml" in file_names:
        analysis["language"] = "python"
    elif "package.json" in file_names:
        analysis["language"] = "javascript"
    elif "go.mod" in file_names:
        analysis["language"] = "go"

    # Framework detection
    if analysis["language"] == "python":
        if (project_path / "manage.py").exists():
            if (project_path / "settings.py").exists():
                analysis["framework"] = "django"
        elif (project_path / "main.py").exists():
            content = (project_path / "main.py").read_text()
            if "FastAPI" in content:
                analysis["framework"] = "fastapi"
            elif "Flask" in content:
                analysis["framework"] = "flask"

    # Test framework
    if analysis["language"] == "python":
        if "pytest.ini" in file_names or "pyproject.toml" in file_names:
            analysis["test_framework"] = "pytest"
        elif (project_path / "tests").exists():
            analysis["test_framework"] = "unittest"

    # Package manager
    if "requirements.txt" in file_names:
        analysis["package_manager"] = "pip"
    elif "pyproject.toml" in file_names:
        analysis["package_manager"] = "poetry"
    elif "package.json" in file_names:
        analysis["package_manager"] = "npm"

    # Lint tools
    if "pyproject.toml" in file_names:
        try:
            content = (project_path / "pyproject.toml").read_text()
            if "[tool.ruff]" in content:
                analysis["lint_tools"].append("ruff")
            if "[tool.mypy]" in content:
                analysis["type_checker"] = "mypy"
            if "[tool.black]" in content:
                analysis["format_tool"] = "black"
        except Exception:
            pass

    # Git workflow
    if (project_path / ".github" / "workflows").exists():
        analysis["ci_cd"] = "github-actions"

    # Docs
    analysis["has_readme"] = "README.md" in file_names
    analysis["has_docker"] = "Dockerfile" in file_names or "docker-compose.yml" in file_names

    return analysis


def generate_rules(project_path: Path, analysis: dict) -> dict[str, Any]:
    """Generate rules based on analysis."""
    rules = {
        "code_style": {
            "naming": {
                "files": "snake_case",
                "classes": "PascalCase",
                "functions": "snake_case",
            },
            "formatting": {
                "indent": "4 spaces",
                "max_line_length": "100",
            },
        },
        "testing": {
            "framework": analysis.get("test_framework", "pytest"),
            "patterns": ["test_*.py", "*_test.py"],
        },
        "validation": {
            "lint": {
                "tool": analysis.get("lint_tools", ["ruff"])[0] if analysis.get("lint_tools") else "ruff",
            },
        },
        "git": {
            "commits": {
                "format": "type(scope): description",
                "types": ["feat", "fix", "docs", "style", "refactor", "test", "chore"],
            },
            "branch": "main",
        },
    }

    # Customize based on framework
    if analysis.get("framework") == "django":
        rules["code_style"]["naming"]["models"] = "PascalCase"
        rules["code_style"]["naming"]["views"] = "snake_case"
    elif analysis.get("framework") == "fastapi":
        rules["code_style"]["naming"]["routers"] = "snake_case"

    return rules


def load_project_rules(
    project_path: Path,
    rules_dir: Path | None = None,
    force_refresh: bool = False,
) -> ProjectRules:
    """Load project rules with smart fallback."""

    # Check if specific rules_dir provided
    if rules_dir and rules_dir.exists():
        rules = _load_from_directory(rules_dir)
        if rules:
            return rules

    # Check cached rules
    existing = ProjectRules.load(project_path)
    if existing and not force_refresh:
        return existing

    # Analyze and generate new rules
    if force_refresh or not existing:
        analysis = analyze_project(project_path)
        rules_dict = generate_rules(project_path, analysis)
        rules = ProjectRules(
            project_path=project_path,
            rules=rules_dict,
            analysis=analysis,
            source_file="auto-generated",
        )
        rules.save()
        return rules

    return existing


def _load_from_directory(rules_dir: Path) -> ProjectRules | None:
    """Load rules from a directory of YAML files."""
    rules = {}
    analysis = {}

    yaml_files = list(rules_dir.glob("*.yaml")) + list(rules_dir.glob("*.yml"))

    for yaml_file in yaml_files:
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
                if data:
                    rules.update(data)
        except Exception:
            pass

    if not rules:
        return None

    return ProjectRules(
        project_path=rules_dir.parent,
        rules=rules,
        analysis=analysis,
        source_file=str(rules_dir),
    )


def get_default_rules() -> dict[str, Any]:
    """Get default rules."""
    return yaml.safe_load(DEFAULT_RULES)


_rules_cache: dict[str, ProjectRules] = {}


def get_rules(project_path: Path | None = None, rules_dir: Path | None = None) -> ProjectRules:
    """Get cached or fresh rules."""
    from .project import detect_project

    if project_path:
        root = project_path
    else:
        ctx = detect_project()
        root = ctx.root

    root_str = str(root.resolve())

    if root_str in _rules_cache:
        return _rules_cache[root_str]

    rules = load_project_rules(root, rules_dir)
    _rules_cache[root_str] = rules
    return rules
