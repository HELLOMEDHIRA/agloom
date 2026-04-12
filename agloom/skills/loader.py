"""Factory for the load_skill BaseTool given to every worker."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..logging_utils import get_logger

logger = get_logger(__name__)


def make_load_skill_tool(registry: Any) -> StructuredTool:
    """Build the load_skill BaseTool bound to a SkillRegistry."""
    # Sync factory: cannot await the registry, so the tool description is fixed text.
    description = (
        "Load full instructions for a named agent skill. "
        "Call this at the START of your task if a relevant skill is available. "
        "Returns step-by-step instructions, prompt hints, and available resources. "
        "Use the skill name exactly as shown in the available skills list."
    )

    class LoadSkillInput(BaseModel):
        name: str = Field(description="Exact skill name to load (e.g. 'github-search', 'code-review')")

    async def load_skill(name: str) -> str:
        content = await registry.get_content(name)
        if content is None:
            available = await registry.list_manifests()
            names = [m.name for m in available]
            return f"Skill '{name}' not found.\nAvailable skills: {names}\nUse one of the exact names listed above."
        logger.debug(f"load_skill: loaded '{name}' ({len(content.body)} chars)")
        return content.to_system_prompt_block()

    return StructuredTool(
        name="load_skill",
        description=description,
        args_schema=LoadSkillInput,
        coroutine=load_skill,
    )
