"""Core data models: SkillManifest, SkillContent, AgentSkill."""

from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


@dataclass
class SkillManifest:
    """Lightweight manifest (name + description) — what the classifier sees at runtime."""

    name: str
    description: str
    path: Path = field(default_factory=lambda: Path(""))
    compatibility: str = ""
    tags: list[str] = field(default_factory=list)
    scope: str = "global"
    source: str = "static"
    status: str = "active"
    version: int = 1

    def classifier_line(self) -> str:
        tag_hint = f" [{', '.join(self.tags)}]" if self.tags else ""
        return f"  - [{self.name}]{tag_hint}: {self.description}"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "compatibility": self.compatibility,
            "tags": self.tags,
            "scope": self.scope,
            "source": self.source,
            "status": self.status,
            "version": self.version,
        }

    @classmethod
    def from_metadata(cls, meta: dict[str, Any]) -> SkillManifest | None:
        name = meta.get("name", "").strip()
        desc = meta.get("description", "").strip()
        if not name or not desc:
            return None
        return cls(
            name=name,
            description=desc,
            compatibility=meta.get("compatibility", ""),
            tags=meta.get("tags", []),
            scope=meta.get("scope", "global"),
            source=meta.get("source", "static"),
            status=meta.get("status", "active"),
            version=meta.get("version", 1),
        )


@dataclass
class SkillContent:
    """Full SKILL.md content: manifest + body + sibling file listings."""

    manifest: SkillManifest
    body: str
    scripts: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    skill_data: dict[str, Any] | None = None

    def to_system_prompt_block(self) -> str:
        """Format for injection into worker system_prompt."""
        lines = [
            f"=== SKILL: {self.manifest.name} ===",
            self.body.strip(),
        ]
        if self.references:
            lines.append(f"\nReference files available: {self.references}")
        if self.assets:
            lines.append(f"Asset files available: {self.assets}")
        if self.scripts:
            lines.append(f"Scripts available: {self.scripts}")
        lines.append(f"=== END SKILL: {self.manifest.name} ===")
        return "\n".join(lines)

    def to_lts_metadata(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            **self.manifest.to_metadata(),
            "body": self.body,
            "scripts": self.scripts,
            "references": self.references,
            "assets": self.assets,
            "examples": self.examples,
        }
        if self.skill_data:
            out["skill_data"] = self.skill_data
        return out

    @classmethod
    def from_lts_metadata(cls, meta: dict[str, Any]) -> SkillContent | None:
        manifest = SkillManifest.from_metadata(meta)
        if not manifest:
            return None
        return cls(
            manifest=manifest,
            body=meta.get("body", ""),
            scripts=meta.get("scripts", []),
            references=meta.get("references", []),
            assets=meta.get("assets", []),
            examples=meta.get("examples", []),
            skill_data=meta.get("skill_data"),
        )


class AgentSkill(BaseModel):
    """Learned agent behaviour extracted from a successful run."""

    skill_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str
    description: str
    trigger: str
    pattern: str
    tool_names: list[str] = Field(default_factory=list)
    worker_plan: list[dict] = Field(default_factory=list)
    prompt_hints: str = ""
    example_query: str = ""
    scope: str = "global"
    success_count: int = 1
    failure_count: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_used: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def confidence(self) -> float:
        total = self.success_count + self.failure_count
        return round(self.success_count / total, 2) if total > 0 else 0.5

    def should_prune(self) -> bool:
        return (self.success_count + self.failure_count) >= 5 and self.confidence() < 0.2

    def to_manifest(self) -> SkillManifest:
        return SkillManifest(
            name=self.name,
            description=self.description,
            scope=self.scope,
            source="learned",
            tags=["learned", self.pattern.lower()],
        )

    def to_content_body(self) -> str:
        workers_text = (
            "\n".join(
                f"  - worker '{w.get('worker_id', 'worker')}': "
                f"task='{w.get('task_description', '')}' "
                f"tools={w.get('tool_names', [])}"
                for w in self.worker_plan
            )
            or "  (single worker)"
        )

        return f"""## When To Use

{self.trigger}

## Approach

- Pattern: **{self.pattern}**
- Tools: {self.tool_names}

## Worker Plan

{workers_text}

## Prompt Hints

{self.prompt_hints or "No specific prompt hints."}

## Example

Query: "{self.example_query}"

## Confidence

{self.confidence():.0%} ({self.success_count} successes, {self.failure_count} failures)
""".strip()

    def to_lts_index_text(self) -> str:
        return (
            f"learned-skill:{self.name} | trigger:{self.trigger} | "
            f"pattern:{self.pattern} | tools:{self.tool_names} | "
            f"description:{self.description} | example:{self.example_query[:120]}"
        )

    def to_lts_metadata(self) -> dict[str, Any]:
        return {
            **self.to_manifest().to_metadata(),
            "body": self.to_content_body(),
            "skill_data": self.model_dump(),
        }


def skill_dir_slug(name: str) -> str:
    """Filesystem-safe directory name for a skill (under a skills root)."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name.strip())
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "skill"


def parse_skill_md(path: Path) -> SkillManifest | None:
    """Parse YAML frontmatter only (not the body) from a SKILL.md file."""
    try:
        text = path.read_text(encoding="utf-8")
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if not match:
            return None
        front = yaml.safe_load(match.group(1)) or {}
        name = str(front.get("name", "")).strip()
        desc = str(front.get("description", "")).strip()
        if not name or not desc:
            return None

        # Block scalars can span lines; classifier expects a single line.
        desc = " ".join(desc.split())

        ver = front.get("version", 1)
        try:
            version = int(ver)
        except (TypeError, ValueError):
            version = 1

        return SkillManifest(
            name=name,
            description=desc,
            path=path,
            compatibility=str(front.get("compatibility", "")),
            tags=list(front.get("tags", [])),
            scope=str(front.get("scope", "global")),
            source=str(front.get("source", "static")),
            status=str(front.get("status", "active")),
            version=version,
        )
    except Exception:
        return None


def load_skill_content(manifest: SkillManifest) -> SkillContent:
    """Load the full SKILL.md body and scan sibling directories."""
    text = manifest.path.read_text(encoding="utf-8") if manifest.path != Path("") else ""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    skill_data: dict[str, Any] | None = None
    if match:
        front = yaml.safe_load(match.group(1)) or {}
        raw_sd = front.get("skill_data")
        if isinstance(raw_sd, dict):
            skill_data = raw_sd
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL).strip()
    root = manifest.path.parent

    def _list_dir(subdir: str) -> list[str]:
        d = root / subdir
        return [p.name for p in d.iterdir()] if d.exists() else []

    return SkillContent(
        manifest=manifest,
        body=body,
        scripts=_list_dir("scripts"),
        references=_list_dir("references"),
        assets=_list_dir("assets"),
        examples=_list_dir("examples"),
        skill_data=skill_data,
    )


def write_skill_md(
    skills_root: Path,
    manifest: SkillManifest,
    body: str,
    skill_data: dict[str, Any] | None = None,
) -> Path:
    """Write ``<skills_root>/<slug>/SKILL.md`` and return the file path."""
    slug = skill_dir_slug(manifest.name)
    dir_path = skills_root / slug
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / "SKILL.md"
    front: dict[str, Any] = {
        "name": manifest.name,
        "description": manifest.description,
        "scope": manifest.scope,
        "source": manifest.source,
        "tags": manifest.tags,
        "version": manifest.version,
    }
    if manifest.compatibility:
        front["compatibility"] = manifest.compatibility
    if manifest.status and manifest.status != "active":
        front["status"] = manifest.status
    if skill_data:
        front["skill_data"] = skill_data
    yaml_body = yaml.safe_dump(front, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()
    path.write_text(f"---\n{yaml_body}\n---\n\n{body.strip()}\n", encoding="utf-8")
    return path


def erase_skill_md_tree(skills_root: Path, skill_name: str) -> bool:
    """Remove ``<skills_root>/<slug>/`` if it exists. Returns True if a directory was removed."""
    slug = skill_dir_slug(skill_name)
    target = skills_root / slug
    if target.is_dir():
        shutil.rmtree(target)
        return True
    return False
