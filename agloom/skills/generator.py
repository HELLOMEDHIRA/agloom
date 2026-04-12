"""LLM-driven seed skill generation from tool inventory."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, field_validator

from ..logging_utils import get_logger

logger = get_logger(__name__)


SEED_SYSTEM_PROMPT = """
You are an Agent Skill Architect.

Given a list of tools an AI agent has access to, generate an initial
skill library. Each skill represents a REUSABLE TASK PATTERN — a class
of problems this agent will commonly face.

Rules:
- Group related tools into meaningful task patterns
- Name skills in kebab-case (web-research, code-review, data-analysis)
- description must be ONE sentence with trigger keywords (classifier reads this)
- body must be concrete step-by-step instructions, not vague guidelines
- Generate 3-7 skills max — quality over quantity
- Do NOT create a skill per tool — create skills for TASK PATTERNS
""".strip()


class GeneratedSkill(BaseModel):
    name: str
    description: str
    body: str

    @field_validator("body", mode="before")
    @classmethod
    def _coerce_body(cls, v: Any) -> str:
        if isinstance(v, list):
            return "\n".join(str(item) for item in v)
        return v


class GeneratedSkillList(BaseModel):
    skills: list[GeneratedSkill]


class SkillGenerator:
    """Generates seed skills from tool inventory and on-demand skills for unmatched queries."""

    def __init__(
        self,
        llm: Any,
        llm_timeout: float = 30.0,
        structured_max_retries: int = 2,
    ) -> None:
        self._llm = llm
        self._timeout = llm_timeout
        self._max_retries = structured_max_retries

    async def generate_seed_skills(
        self,
        tools: list[BaseTool],
        agent_name: str = "Agent",
    ) -> list[GeneratedSkill]:
        """Generate initial skill library from the agent's tool list."""
        if not tools:
            logger.info(f"SkillGenerator [{agent_name}]: no tools — no seed skills")
            return []

        tool_descriptions = "\n".join(
            f"  - {t.name}: {t.description}"
            for t in tools
            if t.name != "load_skill"  # Meta-tool; not a domain capability to pattern-match.
        )

        prompt = f"""
Agent name  : {agent_name}
Agent tools :
{tool_descriptions}

Generate an initial skill library for this agent.
Each skill should represent a common task pattern this agent will face.
""".strip()

        try:
            from ..llm_utils import robust_structured_call

            result = await robust_structured_call(
                self._llm,
                GeneratedSkillList,
                [
                    SystemMessage(content=SEED_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ],
                max_retries=self._max_retries,
                timeout=self._timeout,
                caller=f"SkillGenerator[{agent_name}]",
            )
            if result is None:
                logger.warning(f"SkillGenerator [{agent_name}]: seed generation returned None")
                return []
            logger.info(
                f"SkillGenerator [{agent_name}]: "
                f"generated {len(result.skills)} seed skill(s): "
                f"{[s.name for s in result.skills]}"
            )
            return result.skills
        except Exception as e:
            logger.error(f"SkillGenerator [{agent_name}]: seed generation failed: {e}")
            return []

    async def generate_for_query(
        self,
        query: str,
        tools: list[BaseTool],
        agent_name: str = "Agent",
    ) -> GeneratedSkill | None:
        """Generate a skill template for an unmatched query (background, non-blocking)."""
        tool_names = [t.name for t in tools if t.name != "load_skill"]

        prompt = f"""
A query arrived that matches no existing skill:
Query: "{query}"

Available tools: {tool_names}

Generate ONE skill that would handle this class of queries well.
The skill name should be general enough to cover similar future queries.
""".strip()

        try:
            from ..llm_utils import robust_structured_call

            skill = await robust_structured_call(
                self._llm,
                GeneratedSkill,
                [
                    SystemMessage(content=SEED_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ],
                max_retries=self._max_retries,
                timeout=self._timeout,
                caller=f"SkillGenerator[{agent_name}]",
            )
            if skill is None:
                logger.warning(f"SkillGenerator [{agent_name}]: query-driven generation returned None")
                return None
            logger.info(f"SkillGenerator [{agent_name}]: query-driven skill generated: '{skill.name}'")
            return skill
        except Exception as e:
            logger.error(f"SkillGenerator [{agent_name}]: query-driven generation failed: {e}")
            return None
