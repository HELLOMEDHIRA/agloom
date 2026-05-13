"""SKILL.md disk mirror and layout helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.store.memory import InMemoryStore

from agloom.memory.store import LongTermStore
from agloom.skills.registry import SkillRegistry, set_extra_skill_dirs
from agloom.skills.skill import (
    SkillManifest,
    erase_skill_md_tree,
    load_skill_content,
    parse_skill_md,
    skill_dir_slug,
    write_skill_md,
)


def test_skill_dir_slug() -> None:
    assert skill_dir_slug("a/b") == "a-b"
    assert skill_dir_slug("  my skill  ") == "my skill"
    assert skill_dir_slug("..") == "skill"
    assert skill_dir_slug("..evil") == "skill"
    assert skill_dir_slug("...") == "skill"


def test_write_and_parse_skill_md_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    manifest = SkillManifest(
        name="demo-skill",
        description="A demo skill for tests.",
        scope="global",
        source="learned",
        tags=["learned", "test"],
        version=2,
    )
    write_skill_md(root, manifest, "## Body\n\nHello.", skill_data={"foo": 1})
    path = root / "demo-skill" / "SKILL.md"
    assert path.is_file()
    parsed = parse_skill_md(path)
    assert parsed is not None
    assert parsed.name == "demo-skill"
    assert parsed.source == "learned"
    assert parsed.version == 2
    content = load_skill_content(parsed)
    assert "Hello." in content.body
    assert content.skill_data == {"foo": 1}


def test_erase_skill_md_tree(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    write_skill_md(
        root,
        SkillManifest(name="x", description="d", source="learned"),
        "body",
    )
    assert erase_skill_md_tree(root, "x")
    assert not (root / "x").exists()
    assert not erase_skill_md_tree(root, "x")


@pytest.mark.asyncio
async def test_registry_mirrors_learned_skill_to_disk(tmp_path: Path) -> None:
    store = LongTermStore(InMemoryStore())
    mirror = tmp_path / "skills"
    reg = SkillRegistry(store, "test-agent", disk_mirror=mirror)
    await reg.save_learned_skill(
        "file-ops",
        "File helpers",
        "## When\n\nUse for files.",
        skill_data=None,
    )
    skill_file = mirror / "file-ops" / "SKILL.md"
    assert skill_file.is_file()
    assert await reg.remove_skill("file-ops", scope="global")
    assert not skill_file.parent.exists()


def test_set_extra_skill_dirs_prepends_search_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_SKILLS_DIR", raising=False)
    extra = str(tmp_path / "extra_skills")
    set_extra_skill_dirs([extra])
    from agloom.skills import registry as reg_mod

    reg_mod._cached_skill_dirs = None
    dirs = reg_mod._resolve_skill_dirs()
    assert dirs[0] == extra
    set_extra_skill_dirs([])
    reg_mod._cached_skill_dirs = None
