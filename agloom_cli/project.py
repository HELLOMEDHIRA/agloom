"""Project context detection and management."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

SUPPORTED_LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".scala": "scala",
}

FRAMEWORK_PATTERNS = {
    "python": {
        "django": ["manage.py", "settings.py", "wsgi.py"],
        "flask": ["app.py", "main.py"],
        "fastapi": ["main.py", "app.py"],
        "django-ninja": ["api.py"],
        "celery": ["celery.py"],
        "pytest": ["pytest.ini", "conftest.py", "tests/"],
    },
    "javascript": {
        "express": ["server.js", "app.js", "index.js"],
        "next": ["next.config.js", "next.config.mjs"],
        "nuxt": ["nuxt.config.js", "nuxt.config.ts"],
        "svelte": ["svelte.config.js"],
        "vite": ["vite.config.js", "vite.config.ts"],
        "webpack": ["webpack.config.js"],
    },
    "typescript": {
        "express": ["server.ts", "app.ts"],
        "next": ["next.config.js", "next.config.ts"],
        "nest": ["nest-cli.json"],
        "fastify": ["fastify.config.ts"],
    },
    "go": {
        "gin": ["main.go"],
        "echo": ["main.go"],
        "fiber": ["main.go"],
    },
    "rust": {
        "actix": ["src/main.rs"],
        "axum": ["src/main.rs"],
        "rocket": ["src/main.rs"],
    },
}

DETECT_FILES = [
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Pipfile",
    "poetry.lock",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "composer.json",
    "Gemfile",
    "Makefile",
    "CMakeLists.txt",
    "setup.py",
    "setup.cfg",
]


class ProjectContext:
    """Represents detected project context."""

    def __init__(
        self,
        root: Path,
        language: str | None = None,
        frameworks: list[str] | None = None,
        project_type: str | None = None,
        dependencies: dict[str, str] | None = None,
        has_tests: bool = False,
        has_lint: bool = False,
        has_docker: bool = False,
    ):
        self.root = root
        self.language = language or "unknown"
        self.frameworks = frameworks or []
        self.project_type = project_type or "library"
        self.dependencies = dependencies or {}
        self.has_tests = has_tests
        self.has_lint = has_lint
        self.has_docker = has_docker

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "language": self.language,
            "frameworks": self.frameworks,
            "project_type": self.project_type,
            "dependencies": self.dependencies,
            "has_tests": self.has_tests,
            "has_lint": self.has_lint,
            "has_docker": self.has_docker,
        }


def detect_language(root: Path, max_files: int = 50) -> str | None:
    """Detect primary language from file extensions - limited scan."""
    language_counts: dict[str, int] = {}

    def _scan_dir(path: Path, depth: int = 0):
        if depth > 2 or len(language_counts) >= max_files:
            return
        try:
            for item in path.iterdir():
                if len(language_counts) >= max_files:
                    return
                if item.is_file() and item.stat().st_size < 500000:
                    ext = item.suffix.lower()
                    if ext in SUPPORTED_LANGUAGES:
                        lang = SUPPORTED_LANGUAGES[ext]
                        language_counts[lang] = language_counts.get(lang, 0) + 1
                elif item.is_dir() and not item.name.startswith("."):
                    _scan_dir(item, depth + 1)
        except PermissionError:
            pass

    _scan_dir(root)

    if not language_counts:
        return None

    return max(language_counts, key=lambda lang: language_counts[lang])


def detect_frameworks(root: Path, language: str) -> list[str]:
    """Detect frameworks from file patterns."""
    if language not in FRAMEWORK_PATTERNS:
        return []

    detected = []
    patterns = FRAMEWORK_PATTERNS[language]

    for framework, files in patterns.items():
        for pattern_file in files:
            if (root / pattern_file).exists():
                detected.append(framework)
                break

    return detected


def detect_project_type(root: Path, language: str) -> str:
    """Detect if project is library, app, or service."""
    # Check for web app indicators
    if (root / "templates").exists() or (root / "public").exists():
        return "webapp"

    # Check for API indicators
    if (root / "routes").exists() or (root / "api").exists():
        return "api"

    # Check for CLI tool
    if (root / "cli").exists() or (root / "cmd").exists():
        return "cli"

    # Check for library/package
    if language == "python":
        if (root / "src").exists() or not (root / "tests").exists():
            return "library"

    return "application"


def detect_dependencies(root: Path, language: str) -> dict[str, str]:
    """Detect dependencies from package files."""
    deps = {}

    if language == "python":
        # requirements.txt
        req_file = root / "requirements.txt"
        if req_file.exists():
            for line in req_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    if "==" in line:
                        pkg, ver = line.split("==", 1)
                        deps[pkg.strip()] = ver.strip()
                    else:
                        deps[line] = "*"

        # pyproject.toml
        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            try:
                import tomli

                with open(pyproject, "rb") as f:
                    data = tomli.load(f)
                    if "project" in data and "dependencies" in data["project"]:
                        for dep in data["project"]["dependencies"]:
                            deps[dep] = "*"
            except Exception:
                pass

    elif language in ("javascript", "typescript"):
        package_json = root / "package.json"
        if package_json.exists():
            try:
                import json

                with open(package_json) as f:
                    data = json.load(f)
                    deps.update(data.get("dependencies", {}))
                    deps.update(data.get("devDependencies", {}))
            except Exception:
                pass

    elif language == "go":
        go_mod = root / "go.mod"
        if go_mod.exists():
            content = go_mod.read_text()
            in_require_block = False
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("require ("):
                    in_require_block = True
                    continue
                if in_require_block and stripped == ")":
                    in_require_block = False
                    continue
                if in_require_block or (
                    " " in line and not stripped.startswith("module") and not stripped.startswith("require")
                ):
                    parts = stripped.split()
                    if len(parts) >= 2:
                        deps[parts[0]] = parts[1]

    return deps


def detect_test_framework(root: Path, language: str) -> bool:
    """Check if project has tests."""
    test_dirs = ["tests", "test", "__tests__", "specs"]
    test_patterns = {
        "python": ["test_*.py", "*_test.py", "conftest.py"],
        "javascript": ["*.test.js", "*.spec.js", "__tests__"],
        "typescript": ["*.test.ts", "*.spec.ts", "__tests__"],
    }

    for test_dir in test_dirs:
        if (root / test_dir).exists():
            return True

    if language in test_patterns:
        for pattern in test_patterns[language]:
            if list(root.rglob(pattern)):
                return True

    return False


def detect_linter(root: Path, language: str) -> bool:
    """Check if project has linting configured."""
    lint_files = [
        ".eslintrc",
        ".eslintrc.js",
        ".eslintrc.json",
        "pytest.ini",
        "pyproject.toml",
        ".pylintrc",
        "pylintrc",
        "rustfmt.toml",
        "gofmt",
    ]

    return any((root / lint_file).exists() for lint_file in lint_files)


def detect_docker(root: Path) -> bool:
    """Check if project has Docker."""
    return (
        (root / "Dockerfile").exists()
        or (root / "docker-compose.yml").exists()
        or (root / "docker-compose.yaml").exists()
    )


_project_cache: dict[str, ProjectContext] = {}


def detect_project(root: Path | None = None) -> ProjectContext:
    """Auto-detect project context from directory - fast scan."""
    root = (root or Path.cwd()).resolve()
    root_str = str(root)

    if root_str in _project_cache:
        return _project_cache[root_str]

    project_root = _find_project_root(root)

    # Quick detection using markers
    language = _detect_language_quick(project_root)
    framework_list = detect_frameworks(project_root, language or "unknown")
    project_type = detect_project_type(project_root, language or "unknown")
    has_tests = detect_test_framework(project_root, language or "unknown")
    has_lint = detect_linter(project_root, language or "unknown")
    has_docker = detect_docker(project_root)

    ctx = ProjectContext(
        root=project_root,
        language=language,
        frameworks=framework_list,
        project_type=project_type,
        dependencies={},
        has_tests=has_tests,
        has_lint=has_lint,
        has_docker=has_docker,
    )

    _project_cache[root_str] = ctx
    return ctx


def _detect_language_quick(root: Path) -> str | None:
    """Quick language detection from markers."""
    markers = {
        "package.json": "javascript",
        "requirements.txt": "python",
        "pyproject.toml": "python",
        "go.mod": "go",
        "Cargo.toml": "rust",
        "pom.xml": "java",
        "composer.json": "php",
    }

    for marker, lang in markers.items():
        if (root / marker).exists():
            return lang

    # Check file counts in first level subdirs (quick)
    counts: dict[str, int] = {}
    try:
        for subdir in root.iterdir():
            if not subdir.is_dir() or subdir.name.startswith("."):
                continue
            try:
                for f in subdir.iterdir():
                    if f.is_file():
                        ext = f.suffix.lower()
                        if ext in SUPPORTED_LANGUAGES:
                            counts[SUPPORTED_LANGUAGES[ext]] = counts.get(SUPPORTED_LANGUAGES[ext], 0) + 1
            except PermissionError:
                pass
    except PermissionError:
        pass

    if counts:
        return max(counts, key=lambda lang: counts[lang])

    return None


def _find_project_root(start: Path) -> Path:
    """Find project root by searching for marker files."""
    # Check git root first
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:
        pass

    # Search for detect files
    current = start.resolve()
    while current != current.parent:
        for detect_file in DETECT_FILES:
            if (current / detect_file).exists():
                return current
        current = current.parent

    return start


def get_git_info(root: Path) -> dict[str, Any]:
    """Get git repository information - with timeout."""
    info = {
        "branch": "main",
        "status": "clean",
        "remote": None,
        "commits_ahead": 0,
    }

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return info

        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            info["branch"] = result.stdout.strip()

        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            info["status"] = "dirty"

    except Exception:
        pass

    return info


def save_project_context(context: ProjectContext, session_id: str, home_dir: Path) -> None:
    """Save project context to session."""
    import json

    session_file = home_dir / "sessions" / f"{session_id}.json"

    if session_file.exists():
        with open(session_file) as f:
            raw = json.load(f)
        default_session: dict[str, Any] = {"id": session_id, "messages": [], "projects": {}}
        session = raw if isinstance(raw, dict) else default_session
    else:
        session = {"id": session_id, "messages": [], "projects": {}}

    if "projects" not in session or not isinstance(session["projects"], dict):
        session["projects"] = {}

    project_key = str(context.root)
    session["projects"][project_key] = context.to_dict()

    with open(session_file, "w") as f:
        json.dump(session, f, indent=2)


def get_session_projects(session_id: str, home_dir: Path) -> list[ProjectContext]:
    """Get all projects from a session."""
    import json

    session_file = home_dir / "sessions" / f"{session_id}.json"

    if not session_file.exists():
        return []

    with open(session_file, encoding="utf-8") as f:
        session = json.load(f)

    projects = []
    for project_data in session.get("projects", {}).values():
        if not isinstance(project_data, dict):
            continue
        try:
            projects.append(ProjectContext(**project_data))
        except (TypeError, ValueError):
            continue

    return projects
