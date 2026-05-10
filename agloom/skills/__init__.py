"""Agent skills: registry, disk format, learning, injection, and lifecycle.

Submodules remain importable directly (e.g. ``from agloom.skills.registry import SkillRegistry``).
``__all__`` lists the symbols most useful from ``import agloom.skills as skills``.
"""

from __future__ import annotations

from .generator import GeneratedSkill, GeneratedSkillList, SkillGenerator
from .injector import SkillInjector
from .learner import SkillLearner
from .lifecycle import ReviewResult, SkillAction, SkillLifecycleManager
from .loader import make_load_skill_tool
from .registry import SkillRegistry, set_extra_skill_dirs
from .skill import (
    AgentSkill,
    SkillContent,
    SkillManifest,
    erase_skill_md_tree,
    load_skill_content,
    parse_skill_md,
    skill_dir_slug,
    write_skill_md,
)

__all__ = [
    "AgentSkill",
    "GeneratedSkill",
    "GeneratedSkillList",
    "ReviewResult",
    "SkillAction",
    "SkillContent",
    "SkillGenerator",
    "SkillInjector",
    "SkillLearner",
    "SkillLifecycleManager",
    "SkillManifest",
    "SkillRegistry",
    "erase_skill_md_tree",
    "load_skill_content",
    "make_load_skill_tool",
    "parse_skill_md",
    "set_extra_skill_dirs",
    "skill_dir_slug",
    "write_skill_md",
]
