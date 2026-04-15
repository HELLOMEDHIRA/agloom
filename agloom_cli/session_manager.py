"""Multi-session management for agloom CLI."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import HomeDir


class SessionManager:
    """Manages multiple project sessions."""

    def __init__(self, home_dir: Path | None = None):
        self.home_dir = home_dir or HomeDir
        self.sessions_dir = self.home_dir / "sessions"

    def create_session(
        self,
        name: str | None = None,
        project_path: str | None = None,
        model: str = "auto",
        project_structure: dict | None = None,
    ) -> dict[str, Any]:
        """Create a new named session with project structure."""
        import uuid

        session_id = uuid.uuid4().hex[:8]

        # Build project structure if not provided
        if not project_structure and project_path:
            from .project import detect_project

            ctx = detect_project(Path(project_path))
            project_structure = {
                "root": str(ctx.root),
                "language": ctx.language,
                "frameworks": ctx.frameworks,
                "project_type": ctx.project_type,
                "has_tests": ctx.has_tests,
                "has_docker": ctx.has_docker,
            }

        session_data = {
            "id": session_id,
            "name": name or project_path or "default",
            "project_path": str(project_path) if project_path else "",
            "model": model,
            "created_at": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
            "turns": 0,
            "messages": [],
            "project_structure": project_structure or {},
            "file_summaries": {},
            "modified_files": [],
        }

        session_file = self.sessions_dir / f"{session_id}.json"
        with open(session_file, "w") as f:
            json.dump(session_data, f, indent=2)

        return session_data

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get session by ID."""
        session_file = self.sessions_dir / f"{session_id}.json"

        if not session_file.exists():
            return None

        with open(session_file) as f:
            return json.load(f)

    def list_sessions(self, include_messages: bool = False) -> list[dict[str, Any]]:
        """List all sessions."""
        if not self.sessions_dir.exists():
            return []

        sessions = []
        for f in self.sessions_dir.glob("*.json"):
            with open(f) as fp:
                try:
                    data = json.load(fp)
                    if not include_messages:
                        # Remove messages for cleaner list
                        data.pop("messages", None)
                    sessions.append(data)
                except json.JSONDecodeError:
                    continue

        return sorted(sessions, key=lambda x: x.get("last_active", ""), reverse=True)

    def update_session(
        self,
        session_id: str,
        messages: list | None = None,
        turns: int | None = None,
    ) -> bool:
        """Update session data."""
        session_file = self.sessions_dir / f"{session_id}.json"

        if not session_file.exists():
            return False

        with open(session_file) as f:
            session = json.load(f)

        if messages is not None:
            session["messages"] = messages

        if turns is not None:
            session["turns"] = turns

        session["last_active"] = datetime.now().isoformat()

        with open(session_file, "w") as f:
            json.dump(session, f, indent=2)

        return True

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        session_file = self.sessions_dir / f"{session_id}.json"

        if not session_file.exists():
            return False

        session_file.unlink()
        return True

    def switch_session(self, session_id: str) -> dict[str, Any] | None:
        """Switch to a different session."""
        session = self.get_session(session_id)

        if not session:
            return None

        # Update last active timestamp
        self.update_session(session_id)

        return session

    def find_session_by_project(self, project_path: str) -> dict[str, Any] | None:
        """Find session by project path."""
        for session in self.list_sessions():
            if session.get("project_path") == project_path:
                return session

        return None

    def merge_sessions(self, source_id: str, target_id: str) -> bool:
        """Merge messages from source session to target."""
        source = self.get_session(source_id)
        target = self.get_session(target_id)

        if not source or not target:
            return False

        # Merge messages
        existing_messages = target.get("messages", [])
        new_messages = source.get("messages", [])
        target["messages"] = existing_messages + new_messages
        target["turns"] = target.get("turns", 0) + source.get("turns", 0)

        with open(self.sessions_dir / f"{target_id}.json", "w") as f:
            json.dump(target, f, indent=2)

        return True


def get_current_session(home_dir: Path | None = None) -> dict[str, Any] | None:
    """Get the current active session from config."""
    from .config import create_default_config

    config = create_default_config()
    current_id = config.get("session", {}).get("current_session")

    if not current_id:
        return None

    home_dir = home_dir or HomeDir
    session_file = home_dir / "sessions" / f"{current_id}.json"

    if not session_file.exists():
        return None

    with open(session_file) as f:
        return json.load(f)


def switch_session_by_id(session_id: str, home_dir: Path | None = None) -> dict[str, Any] | None:
    """Switch to a session by ID and update config."""
    import yaml

    from .config import create_default_config

    home_dir = home_dir or HomeDir
    manager = SessionManager(home_dir)
    session = manager.switch_session(session_id)

    if not session:
        return None

    # Update config with new session
    config = create_default_config()
    config["session"]["current_session"] = session_id
    config["session"]["last_updated"] = datetime.now().isoformat()

    config_path = home_dir / "agloom.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    return session


def list_all_projects(home_dir: Path | None = None) -> list[dict[str, Any]]:
    """List all unique projects across sessions."""
    home_dir = home_dir or HomeDir
    manager = SessionManager(home_dir)

    projects_seen: dict[str, dict] = {}

    for session in manager.list_sessions():
        project_path = session.get("project_path")
        if project_path and project_path not in projects_seen:
            projects_seen[project_path] = {
                "project_path": project_path,
                "session_id": session.get("id"),
                "session_name": session.get("name"),
                "last_active": session.get("last_active"),
                "turns": session.get("turns", 0),
            }

    return sorted(projects_seen.values(), key=lambda x: x.get("last_active", ""), reverse=True)


def generate_file_summaries(project_path: str) -> dict[str, str]:
    """Generate short summaries for each file in project."""
    root = Path(project_path)
    summaries = {}

    # Quick scan limited files
    file_count = 0
    for file_rel in root.rglob("*"):
        if file_count >= 50:
            break
        if not file_rel.is_file():
            continue

        rel = str(file_rel.relative_to(root))
        if any(ignore in rel for ignore in ["__pycache__", ".git", "node_modules", ".agloom"]):
            continue

        try:
            if file_rel.stat().st_size > 50000:
                continue
            content = file_rel.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")

            func_count = len([line for line in lines if line.strip().startswith("def ")])
            class_count = len([line for line in lines if line.strip().startswith("class ")])

            if func_count or class_count:
                summary = f"{class_count} class(es), {func_count} function(s)"
            else:
                summary = f"{len(lines)} lines"

            summaries[rel] = summary
            file_count += 1
        except Exception:
            pass

    return summaries


def update_session_file_summaries(
    session_id: str,
    project_path: str,
    home_dir: Path | None = None,
) -> bool:
    """Update file summaries for a session."""
    home_dir = home_dir or HomeDir
    manager = SessionManager(home_dir)
    session = manager.get_session(session_id)

    if not session:
        return False

    summaries = generate_file_summaries(project_path)
    session["file_summaries"] = summaries

    session_file = home_dir / "sessions" / f"{session_id}.json"
    with open(session_file, "w") as f:
        json.dump(session, f, indent=2)

    return True


def track_modified_file(
    session_id: str,
    file_path: str,
    home_dir: Path | None = None,
) -> bool:
    """Track a file as modified in the session."""
    home_dir = home_dir or HomeDir
    manager = SessionManager(home_dir)
    session = manager.get_session(session_id)

    if not session:
        return False

    modified = session.get("modified_files", [])
    if file_path not in modified:
        modified.append(file_path)

    session["modified_files"] = modified

    session_file = home_dir / "sessions" / f"{session_id}.json"
    with open(session_file, "w") as f:
        json.dump(session, f, indent=2)

    return True


def get_session_context_summary(session: dict) -> str:
    """Get a short summary of session context for system prompt."""
    parts = []

    project_struct = session.get("project_structure", {})
    if project_struct:
        parts.append(f"Project: {project_struct.get('root')}")
        parts.append(f"Language: {project_struct.get('language')}")
        if project_struct.get("frameworks"):
            parts.append(f"Frameworks: {', '.join(project_struct['frameworks'])}")

    file_summaries = session.get("file_summaries", {})
    if file_summaries:
        # Get top 10 files by summary
        key_files = list(file_summaries.keys())[:10]
        parts.append("Files:")
        for f in key_files:
            parts.append(f"  - {f}: {file_summaries[f]}")

    modified = session.get("modified_files", [])
    if modified:
        parts.append(f"Modified: {', '.join(modified[-5:])}")

    return "\n".join(parts)
