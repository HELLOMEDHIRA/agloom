"""Post-run background skill extraction from successful agent trajectories."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from ..logging_utils import get_logger

logger = get_logger(__name__)

_LEARNABLE_PATTERNS = {
    "react",
    "pipeline",
    "supervisor",
    "planner_executor",
    "reflection",
    "swarm",
    "blackboard",
    "hybrid_dag",
}

_EXTRACT_SYSTEM_PROMPT = """
You are an Agent Skill Extractor following the agentskills.io open standard.

Given a completed agent run, decide if it represents a REUSABLE skill worth storing.

Store as a skill ONLY if ALL of these are true:
  1. The task required a non-trivial multi-step approach
  2. The pattern + tool selection was notably effective
  3. A similar query is likely to recur across different sessions
  4. No existing skill already covers this (check the existing_skills list)

NEVER store skills for:
  - One-off queries specific to a single user/session
  - Simple factual lookups
  - Queries that are just slight variations of existing skills

scope rules:
  "global" → applies to ANY agent solving similar tasks (most learned skills)
  "agent"  → specific to this agent's unique domain (rare — only if clearly domain-locked)

Respond with the JSON schema provided.
""".strip()


class _SkillDecision(BaseModel):
    should_store: bool
    reject_reason: str = ""
    name: str = Field("", description="snake_case skill name")
    description: str = Field("", description="One sentence, max 120 chars, include trigger keywords")
    trigger: str = Field("", description="When to use this skill")
    pattern: str = Field("", description="PatternType used: react/pipeline/supervisor/etc")
    tool_names: list[str] = Field(default_factory=list)
    worker_plan: list[dict] = Field(default_factory=list, description="[{worker_id, task_description, tool_names}]")
    prompt_hints: str = ""
    scope: str = Field("global", description="'global' or 'agent'")

    @field_validator("should_store", mode="before")
    @classmethod
    def _coerce_bool(cls, v: Any) -> bool:
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes")
        return v

    @field_validator("tool_names", mode="before")
    @classmethod
    def _coerce_list(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v = v.strip()
            if v in ("", "[]", "null", "none"):
                return []
            import json

            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(i) for i in parsed]
            except (json.JSONDecodeError, ValueError):
                pass
            return [v]
        if v is None:
            return []
        return v

    @field_validator("worker_plan", mode="before")
    @classmethod
    def _coerce_worker_plan(cls, v: Any) -> list[dict]:
        if isinstance(v, str):
            v = v.strip()
            if v in ("", "[]", "null", "none"):
                return []
            import json

            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
            return []
        if v is None:
            return []
        return v


class SkillLearner:
    """Background skill miner — fires after successful runs, never blocks."""

    def __init__(
        self,
        llm: Any,
        registry: Any,
        llm_timeout: float = 30.0,
        structured_max_retries: int = 2,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._timeout = llm_timeout
        self._max_retries = structured_max_retries

    def maybe_learn(
        self,
        result: Any,
        query: str,
        agent_name: str = "Agent",
    ) -> None:
        """Fire-and-forget background task. Never raises, never blocks."""
        pattern_val = result.pattern_used.value.lower() if result.pattern_used else ""
        if not result.success:
            return
        if pattern_val not in _LEARNABLE_PATTERNS:
            return
        if result.steps_taken < 2:
            return

        from ..llm_utils import safe_create_task

        safe_create_task(
            self._extract(result, query, agent_name),
            name=f"skill-learn-{agent_name[:8]}",
        )

    async def _extract(
        self,
        result: Any,
        query: str,
        agent_name: str,
    ) -> None:
        try:
            existing_manifests = await self._registry.list_manifests()
            existing_names = [m.name for m in existing_manifests]

            worker_summary = ""
            if result.worker_results:
                worker_summary = "\n".join(
                    f"  {r.worker_id}: task='{r.task[:80]}' status={r.signal.value}" for r in result.worker_results
                )

            prompt = f"""
Agent         : {agent_name}
Query         : {query}
Pattern       : {result.pattern_used.value if result.pattern_used else "unknown"}
Steps taken   : {result.steps_taken}
Success       : {result.success}
Output preview: {result.output[:300]}

Worker execution:
{worker_summary or "  (single worker, no breakdown)"}

Existing skills (DO NOT duplicate these):
{existing_names}

Should we store this run as a reusable skill?
""".strip()

            from ..llm_utils import robust_structured_call

            decision = await robust_structured_call(
                self._llm,
                _SkillDecision,
                [
                    SystemMessage(content=_EXTRACT_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ],
                max_retries=self._max_retries,
                timeout=self._timeout,
                caller=f"SkillLearner[{agent_name}]",
            )
            if decision is None:
                logger.debug(f"SkillLearner [{agent_name}]: structured call returned None — skipping")
                return

            if not decision.should_store:
                logger.debug(f"SkillLearner [{agent_name}]: rejected — {decision.reject_reason}")
                return

            from .skill import AgentSkill

            skill = AgentSkill(
                name=decision.name,
                description=decision.description,
                trigger=decision.trigger,
                pattern=decision.pattern or result.pattern_used.value,
                tool_names=decision.tool_names,
                worker_plan=decision.worker_plan,
                prompt_hints=decision.prompt_hints,
                example_query=query,
                scope=decision.scope,
            )

            await self._registry.save_learned_skill(
                name=skill.name,
                description=skill.description,
                body=skill.to_content_body(),
                scope=skill.scope,
                tags=["learned", skill.pattern.lower()],
                skill_data=skill.model_dump(),
            )
            logger.info(
                f"SkillLearner [{agent_name}]: "
                f"stored new skill '{skill.name}' "
                f"(scope={skill.scope}, pattern={skill.pattern})"
            )

        except Exception as e:
            logger.warning(f"SkillLearner [{agent_name}]: extraction failed (non-critical): {e}")
