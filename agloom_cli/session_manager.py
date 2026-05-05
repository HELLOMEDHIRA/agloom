"""Session JSON files under ``<storage>/sessions`` (see ``agloom_cli.config.storage_dir``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import storage_dir


def _session_file(session_id: str, home_dir: Path | None = None) -> Path:
    base = home_dir or storage_dir()
    return base / "sessions" / f"{session_id}.json"


def _load_session(session_id: str, home_dir: Path | None = None) -> dict[str, Any] | None:
    path = _session_file(session_id, home_dir)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_session(session_id: str, data: dict[str, Any], home_dir: Path | None = None) -> None:
    path = _session_file(session_id, home_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def generate_file_summaries(project_path: str) -> dict[str, str]:
    """Generate short summaries for each file in project."""
    root = Path(project_path)
    summaries: dict[str, str] = {}
    file_count = 0

    for file_rel in root.rglob("*"):
        if file_count >= 50:
            break
        if not file_rel.is_file():
            continue

        rel = str(file_rel.relative_to(root))
        if any(ignore in rel for ignore in ["__pycache__", ".git", "node_modules", ".agloom", ".venv"]):
            continue
        sensitive_names = {
            ".env",
            ".envrc",
            ".secrets",
            "secrets.json",
            "credentials.json",
            "id_rsa",
            "id_dsa",
            "id_ecdsa",
            "id_ed25519",
        }
        sensitive_suffixes = (".pem", ".key", ".p12", ".pfx")
        base = file_rel.name
        if base in sensitive_names or base.startswith(".env.") or base.lower().endswith(sensitive_suffixes):
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
    session = _load_session(session_id, home_dir)
    if not session:
        return False

    session["file_summaries"] = generate_file_summaries(project_path)
    _save_session(session_id, session, home_dir)
    return True


def track_modified_file(
    session_id: str,
    file_path: str,
    home_dir: Path | None = None,
) -> bool:
    session = _load_session(session_id, home_dir)
    if not session:
        return False

    modified = session.get("modified_files", [])
    if file_path not in modified:
        modified.append(file_path)
    session["modified_files"] = modified
    _save_session(session_id, session, home_dir)
    return True


def get_session_context_summary(session: dict) -> str:
    """Short summary of session context for the system prompt."""
    parts: list[str] = []

    shell_cwd = session.get("shell_cwd")
    if shell_cwd:
        parts.append(
            f"Shell cwd: {shell_cwd} — **read_file**, **write_file**, and other file tools resolve "
            "relative paths against this directory (not necessarily the project line below). "
            "If a file is missing, call **get_working_directory** or use an absolute path."
        )

    project_struct = session.get("project_structure", {})
    if project_struct:
        parts.append(f"Project: {project_struct.get('root')}")
        parts.append(f"Language: {project_struct.get('language')}")
        if project_struct.get("frameworks"):
            parts.append(f"Frameworks: {', '.join(project_struct['frameworks'])}")

    file_summaries = session.get("file_summaries", {})
    if file_summaries:
        key_files = list(file_summaries.keys())[:10]
        parts.append("Files:")
        for f in key_files:
            parts.append(f"  - {f}: {file_summaries[f]}")

    modified = session.get("modified_files", [])
    if modified:
        parts.append(f"Modified: {', '.join(modified[-5:])}")

    return "\n".join(parts)
