"""Pre-classify skill context injection into the classifier prompt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..logging_utils import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SkillInjectContext:
    """Classifier skill block plus manifest names (for AGP ``skill.applied``)."""

    context: str
    skill_names: list[str]


class SkillInjector:
    """Builds skill context strings for injection into classifier prompts."""

    def __init__(
        self,
        registry: Any,
        top_k: int = 5,
    ) -> None:
        self._registry = registry
        self._top_k = top_k

    async def get_context_bundle(self, query: str) -> SkillInjectContext:
        """Semantic-search top_k relevant skills; returns empty context if none found."""
        try:
            manifests = await self._registry.search_skills(
                query=query,
                top_k=self._top_k,
            )
        except Exception as e:
            logger.warning(f"SkillInjector: search failed: {e}")
            return SkillInjectContext(context="", skill_names=[])

        if not manifests:
            return SkillInjectContext(context="", skill_names=[])

        names = [m.name for m in manifests if getattr(m, "name", None)]
        lines = "\n".join(m.classifier_line() for m in manifests)
        context = (
            "=== RELEVANT SKILLS (call load_skill tool to get full instructions) ===\n"
            + lines
            + "\n\nIMPORTANT: If a skill above is relevant to this query, set matched_skill "
            "to the exact skill name. Workers should call load_skill(name) to get full instructions.\n"
            "==================================================================="
        )
        return SkillInjectContext(context=context, skill_names=names)

    async def get_context(self, query: str) -> str:
        """Semantic-search top_k relevant skills; returns "" if none found."""
        return (await self.get_context_bundle(query)).context

    async def get_full_context(self) -> str:
        """Return all skills regardless of query relevance."""
        try:
            return await self._registry.classifier_block()
        except Exception as e:
            logger.warning(f"SkillInjector: full context failed: {e}")
            return ""
