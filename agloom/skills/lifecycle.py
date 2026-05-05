"""Skill library CRUD lifecycle: usage tracking, pruning, review, and archival."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from ..logging_utils import get_logger
from ..memory.store import LongTermStore

logger = get_logger(__name__)

GLOBAL_NS = ("skills", "global")
MAX_SKILLS = 30
PENDING_TTL_DAYS = 7
ARCHIVE_TTL_DAYS = 30
MIN_USES_FOR_PRUNE = 5
PRUNE_CONFIDENCE = 0.20
REVIEW_EVERY_N_RUNS = 25
STALENESS_DAYS = 14
STALENESS_DECAY = 0.15
MODEL_DRIFT_RESET = True


class SkillAction(BaseModel):
    action: str = Field(
        description="KEEP | PRUNE | MERGE | IMPROVE | PROMOTE",
    )
    skill_names: list[str]
    reason: str
    new_name: str = ""
    new_desc: str = ""
    new_body: str = ""

    @field_validator("skill_names", mode="before")
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

    @field_validator("action", mode="before")
    @classmethod
    def _normalize_action(cls, v: Any) -> str:
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("new_body", mode="before")
    @classmethod
    def _coerce_body(cls, v: Any) -> str:
        if isinstance(v, list):
            return "\n".join(str(item) for item in v)
        if v is None:
            return ""
        return v


class ReviewResult(BaseModel):
    actions: list[SkillAction]


class SkillLifecycleManager:
    """Owns the full skill CRUD lifecycle: usage stats, pruning, review, and archival."""

    def __init__(
        self,
        llm: Any,
        store: LongTermStore,
        registry: Any,  # SkillRegistry
        agent_name: str,
        llm_timeout: float = 60.0,
        structured_max_retries: int = 2,
        review_every_n_runs: int = REVIEW_EVERY_N_RUNS,
        max_skills: int = MAX_SKILLS,
    ) -> None:
        self._llm = llm
        self._store = store
        self._registry = registry
        self._agent = agent_name
        self._run_count = 0
        self._agent_ns = ("skills", agent_name)
        self._model_fingerprint = _compute_model_fingerprint(llm)
        self._timeout = llm_timeout
        self._max_retries = structured_max_retries
        self._review_every = review_every_n_runs
        self._max_skills = max_skills

    async def on_startup(self, current_tool_names: set[str]) -> None:
        """Run all startup hygiene: expiry, orphan check, drift, staleness, cap."""
        await asyncio.gather(
            self._expire_archived(),
            self._invalidate_orphaned(current_tool_names),
            self._detect_model_drift(),
            self._decay_stale_skills(),
            self._enforce_cap(),
        )

    async def _expire_archived(self) -> None:
        """Hard-delete skills that have been soft-archived past TTL."""
        cutoff = datetime.now(UTC) - timedelta(days=ARCHIVE_TTL_DAYS)

        for ns in [GLOBAL_NS, self._agent_ns]:
            results = await self._store.asearch(ns, query="archived", top_k=100)
            for r in results:
                meta = getattr(r, "value", {}) or {}
                if meta.get("status") != "archived":
                    continue
                archived_at_str = meta.get("archived_at", "")
                if not archived_at_str:
                    continue
                try:
                    archived_at = datetime.fromisoformat(archived_at_str)
                    if archived_at < cutoff:
                        name = meta.get("name", "")
                        if name:
                            await self._hard_delete(ns, name)
                            logger.info(f"SkillLifecycle [{self._agent}]: TTL expired → hard deleted '{name}'")
                except Exception as e:
                    logger.warning(f"SkillLifecycle: expire check failed: {e}")

    async def _invalidate_orphaned(self, current_tool_names: set[str]) -> None:
        """Soft-archive skills referencing tools no longer in the agent."""
        if not current_tool_names:
            return

        for ns in [GLOBAL_NS, self._agent_ns]:
            results = await self._store.asearch(ns, query="skill", top_k=100)
            for r in results:
                meta = getattr(r, "value", {}) or {}
                if meta.get("status") in ("archived", "deleted"):
                    continue
                tool_refs = meta.get("tool_names", [])
                if not tool_refs:
                    continue
                orphaned = [t for t in tool_refs if t not in current_tool_names]
                if orphaned:
                    name = meta.get("name", "")
                    if name:
                        await self._soft_archive(ns, name, meta, reason=f"orphaned tools: {orphaned}")
                        logger.warning(
                            f"SkillLifecycle [{self._agent}]: "
                            f"archived orphaned skill '{name}' "
                            f"(missing tools: {orphaned})"
                        )

    async def _detect_model_drift(self) -> None:
        """Reset usage stats when the LLM model changes between sessions.

        Skill bodies are model-agnostic and kept; only trust scores are reset.
        """
        if not MODEL_DRIFT_RESET:
            return

        sentinel_key = "__model_fingerprint__"
        for ns in [self._agent_ns, GLOBAL_NS]:
            item = await self._store.aget(ns, sentinel_key)
            old_fp = ""
            if item:
                old_fp = getattr(item, "value", {}).get("fingerprint", "")

            if old_fp == self._model_fingerprint:
                continue

            if old_fp:
                logger.warning(
                    f"SkillLifecycle [{self._agent}]: "
                    f"model drift detected in {ns} "
                    f"(was={old_fp[:30]}, now={self._model_fingerprint[:30]}) "
                    f"— resetting usage stats for fair re-evaluation"
                )
                await self._reset_usage_stats(ns)

            await self._store.asave(
                namespace=ns,
                key=sentinel_key,
                value=f"model:{self._model_fingerprint}",
                metadata={"fingerprint": self._model_fingerprint, "updated_at": datetime.now(UTC).isoformat()},
            )

    async def _reset_usage_stats(self, ns: tuple) -> None:
        """Reset success/failure counts on all skills in a namespace."""
        results = await self._store.asearch(ns, query="skill", top_k=100)
        for r in results:
            meta = getattr(r, "value", {}) or {}
            if meta.get("status") in ("archived", "deleted"):
                continue
            name = meta.get("name", "")
            if not name or name.startswith("__"):
                continue
            meta["success_count"] = 0
            meta["failure_count"] = 0
            meta["model_reset_at"] = datetime.now(UTC).isoformat()
            await self._store.asave(
                namespace=ns,
                key=name,
                value=meta.get("memory", ""),
                metadata=meta,
            )

    async def _decay_stale_skills(self) -> None:
        """Apply confidence penalty to skills unused for STALENESS_DAYS+."""
        cutoff = datetime.now(UTC) - timedelta(days=STALENESS_DAYS)

        for ns in [self._agent_ns, GLOBAL_NS]:
            results = await self._store.asearch(ns, query="skill", top_k=100)
            for r in results:
                meta = getattr(r, "value", {}) or {}
                if meta.get("status") in ("archived", "deleted"):
                    continue
                name = meta.get("name", "")
                if not name or name.startswith("__"):
                    continue

                last_used_str = meta.get("last_used", "")
                if not last_used_str:
                    continue
                try:
                    last_used = datetime.fromisoformat(last_used_str)
                except Exception:
                    continue
                if last_used >= cutoff:
                    continue

                success = meta.get("success_count", 0)
                failure = meta.get("failure_count", 0)
                total = success + failure
                if total < MIN_USES_FOR_PRUNE:
                    continue

                penalty = int(success * STALENESS_DECAY)
                if penalty < 1:
                    continue
                meta["success_count"] = max(0, success - penalty)
                meta["staleness_decayed_at"] = datetime.now(UTC).isoformat()

                new_total = meta["success_count"] + failure
                confidence = meta["success_count"] / new_total if new_total else 0.5

                if confidence < PRUNE_CONFIDENCE:
                    await self._soft_archive(
                        ns,
                        name,
                        meta,
                        reason=f"stale + low confidence {confidence:.0%} (unused since {last_used_str[:10]})",
                    )
                    logger.info(
                        f"SkillLifecycle [{self._agent}]: "
                        f"staleness archived '{name}' "
                        f"(confidence={confidence:.0%}, "
                        f"last_used={last_used_str[:10]})"
                    )
                else:
                    await self._store.asave(
                        namespace=ns,
                        key=name,
                        value=meta.get("memory", ""),
                        metadata=meta,
                    )
                    logger.debug(
                        f"SkillLifecycle [{self._agent}]: "
                        f"staleness decay on '{name}' "
                        f"(-{penalty} success, confidence now {confidence:.0%})"
                    )

    async def _enforce_cap(self) -> None:
        """Force a review cycle if active skill count exceeds MAX_SKILLS."""
        manifests = await self._registry.list_manifests()
        active = [m for m in manifests if m.status == "active"]
        if len(active) > self._max_skills:
            logger.warning(
                f"SkillLifecycle [{self._agent}]: "
                f"{len(active)} skills > max_skills({self._max_skills}) "
                f"— forcing review"
            )
            await self._run_review_cycle()

    def on_run_complete(
        self,
        success: bool,
        applied_skill: str | None = None,
    ) -> None:
        """Update usage stats and fire periodic review. Never blocks."""
        self._run_count += 1

        if applied_skill:
            from ..llm_utils import safe_create_task

            safe_create_task(
                self._update_usage(applied_skill, success),
                name=f"skill-usage-{self._agent}",
            )

        if self._run_count % self._review_every == 0:
            from ..llm_utils import safe_create_task

            safe_create_task(
                self._run_review_cycle(),
                name=f"skill-review-{self._agent}",
            )

    async def _update_usage(self, skill_name: str, success: bool) -> None:
        """Increment usage counts; auto-archive if confidence drops below threshold."""
        for ns in [self._agent_ns, GLOBAL_NS]:
            item = await self._store.aget(ns, skill_name)
            if not item:
                continue
            meta = getattr(item, "value", {}) or {}
            if meta.get("status") in ("archived", "deleted"):
                continue

            meta["success_count"] = meta.get("success_count", 0) + (1 if success else 0)
            meta["failure_count"] = meta.get("failure_count", 0) + (0 if success else 1)
            meta["last_used"] = datetime.now(UTC).isoformat()
            meta["use_count"] = meta.get("use_count", 0) + 1

            total = meta["success_count"] + meta["failure_count"]
            confidence = meta["success_count"] / total if total else 0.5

            if total >= MIN_USES_FOR_PRUNE and confidence < PRUNE_CONFIDENCE:
                await self._soft_archive(
                    ns, skill_name, meta, reason=f"low confidence {confidence:.0%} after {total} uses"
                )
                logger.warning(
                    f"SkillLifecycle [{self._agent}]: auto-archived '{skill_name}' (confidence={confidence:.0%})"
                )
            else:
                await self._store.asave(
                    namespace=ns,
                    key=skill_name,
                    value=meta.get("memory", ""),
                    metadata=meta,
                )
            break

    async def _run_review_cycle(self) -> None:
        """LLM-driven review: PRUNE, MERGE, IMPROVE, PROMOTE, or KEEP."""
        try:
            manifests = await self._registry.list_manifests()
            active = [m for m in manifests if m.status == "active"]
            if len(active) < 3:
                return

            skill_summaries = []
            for m in active:
                content = await self._registry.get_content(m.name)
                if not content:
                    continue
                meta = content.to_lts_metadata()
                skill_summaries.append(
                    f"name: {m.name}\n"
                    f"description: {m.description}\n"
                    f"source: {meta.get('source', 'unknown')}\n"
                    f"scope: {meta.get('scope', 'global')}\n"
                    f"uses: {meta.get('use_count', 0)} "
                    f"success: {meta.get('success_count', 0)} "
                    f"failures: {meta.get('failure_count', 0)}\n"
                    f"last_used: {meta.get('last_used', 'never')}\n"
                    f"body_preview: {content.body[:200]}\n"
                )

            prompt = f"""
Review {len(active)} skills in the agent '{self._agent}' skill library.
max_skills limit is {self._max_skills}. Currently at {len(active)}.
Current model: {self._model_fingerprint}

{chr(10).join(f"--- SKILL {i + 1} ---{chr(10)}{s}" for i, s in enumerate(skill_summaries))}

Actions to consider:
- PRUNE:   delete low-value, too-specific, or consistently failing skills
- MERGE:   combine near-duplicates into one stronger skill
- IMPROVE: rewrite vague skill bodies with concrete instructions
- PROMOTE: move agent-specific skill to global scope (benefits all agents)
- KEEP:    skill is healthy, no action

If over max_skills, you MUST prune or merge enough to get under the limit.
Skills with model_reset_at set recently had their stats reset due to a model change — give them a chance before pruning.
""".strip()

            from ..llm_utils import robust_structured_call

            result = await robust_structured_call(
                self._llm,
                ReviewResult,
                [
                    SystemMessage(content=_REVIEW_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ],
                max_retries=self._max_retries,
                timeout=self._timeout,
                caller=f"SkillLifecycle[{self._agent}]",
            )
            if result is None:
                logger.warning(f"SkillLifecycle [{self._agent}]: review returned None — skipping")
                return

            for action in result.actions:
                await self._apply_action(action)

            logger.info(f"SkillLifecycle [{self._agent}]: review done — {len(result.actions)} action(s)")

        except Exception as e:
            logger.warning(f"SkillLifecycle [{self._agent}]: review failed: {e}")

    async def _apply_action(self, action: SkillAction) -> None:
        """Apply one review action."""
        try:
            a = action.action.upper()

            if a == "PRUNE":
                for name in action.skill_names:
                    ns = await self._find_ns(name)
                    if ns:
                        item = await self._store.aget(ns, name)
                        meta = getattr(item, "value", {}) or {}
                        await self._soft_archive(ns, name, meta, reason=action.reason)
                logger.info(f"SkillLifecycle: PRUNE {action.skill_names} — {action.reason}")

            elif a == "MERGE" and action.new_name:
                await self._registry.save_learned_skill(
                    name=action.new_name,
                    description=action.new_desc,
                    body=action.new_body,
                    scope="global",
                )
                for name in action.skill_names:
                    ns = await self._find_ns(name)
                    if ns:
                        item = await self._store.aget(ns, name)
                        meta = getattr(item, "value", {}) or {}
                        await self._soft_archive(ns, name, meta, reason=f"merged into '{action.new_name}'")
                logger.info(f"SkillLifecycle: MERGE {action.skill_names} → '{action.new_name}'")

            elif a == "IMPROVE" and action.skill_names:
                name = action.skill_names[0]
                ns = await self._find_ns(name) or GLOBAL_NS
                await self._registry.save_learned_skill(
                    name=action.new_name or name,
                    description=action.new_desc,
                    body=action.new_body,
                    scope="global",
                )
                if action.new_name and action.new_name != name:
                    item = await self._store.aget(ns, name)
                    meta = getattr(item, "value", {}) or {}
                    await self._soft_archive(ns, name, meta, reason=f"improved and renamed to '{action.new_name}'")
                logger.info(f"SkillLifecycle: IMPROVE '{name}' → '{action.new_name or name}'")

            elif a == "PROMOTE":
                for name in action.skill_names:
                    ns = await self._find_ns(name)
                    if ns and ns != GLOBAL_NS:
                        item = await self._store.aget(ns, name)
                        meta = getattr(item, "value", {}) or {}
                        content = await self._registry.get_content(name)
                        if content:
                            await self._registry.save_learned_skill(
                                name=name,
                                description=content.manifest.description,
                                body=content.body,
                                scope="global",
                            )
                            await self._soft_archive(ns, name, meta, reason="promoted to global scope")
                logger.info(f"SkillLifecycle: PROMOTE {action.skill_names} → global")

        except Exception as e:
            logger.warning(f"SkillLifecycle: action {action.action} failed: {e}")

    async def _soft_archive(
        self,
        ns: tuple,
        name: str,
        meta: dict,
        reason: str = "",
    ) -> None:
        """Mark as archived; hard-deleted automatically after ARCHIVE_TTL_DAYS."""
        meta["status"] = "archived"
        meta["archived_at"] = datetime.now(UTC).isoformat()
        meta["archive_reason"] = reason
        await self._store.asave(
            namespace=ns,
            key=name,
            value=f"archived:{name}",
            metadata=meta,
        )
        self._registry._cache.pop(name, None)

    async def _hard_delete(self, ns: tuple, name: str) -> None:
        """Permanent deletion — only after TTL expiry or review cycle."""
        await self._registry.remove_skill_at(ns, name)

    async def _find_ns(self, name: str) -> tuple | None:
        """Find which namespace a skill lives in."""
        for ns in [self._agent_ns, GLOBAL_NS]:
            result = await self._store.aget(ns, name)
            if result:
                return ns
        return None


_fingerprint_cache: dict[int, str] = {}
_FINGERPRINT_CACHE_MAX = 32


def _compute_model_fingerprint(llm: Any) -> str:
    """Config-level identity string (class + model name + provider) for drift detection. LRU-cached (max 32)."""
    obj_id = id(llm)
    if obj_id in _fingerprint_cache:
        return _fingerprint_cache[obj_id]

    if len(_fingerprint_cache) >= _FINGERPRINT_CACHE_MAX:
        oldest = next(iter(_fingerprint_cache))
        del _fingerprint_cache[oldest]

    parts = [type(llm).__name__]
    for attr in ("model_name", "model", "model_id"):
        val = getattr(llm, attr, None)
        if val:
            parts.append(str(val))
            break
    for attr in ("provider", "base_url", "api_base", "endpoint_url"):
        val = getattr(llm, attr, None)
        if val:
            parts.append(str(val)[:50])
            break
    result = "|".join(parts)
    _fingerprint_cache[obj_id] = result
    return result


_REVIEW_SYSTEM_PROMPT = """
You are an Agent Skill Librarian responsible for keeping the skill
library lean, precise, and high-performing.

Your goal: maximum classifier accuracy with minimum skill count.
A library of 10 precise skills beats 40 vague ones every time.

Review each skill critically. Prefer PRUNE and MERGE over KEEP.
IMPROVE only if the skill is genuinely useful but poorly written.
PROMOTE only if the skill clearly applies to any agent, not just this one.
""".strip()
