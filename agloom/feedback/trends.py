"""Periodic longitudinal performance analysis across agent runs."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, field_validator

if TYPE_CHECKING:
    from .store import FeedbackStore

from ..logging_utils import get_logger

logger = get_logger(__name__)

TREND_EVERY_N_RUNS = 100
MIN_RECORDS_FOR_ANALYSIS = 20

_TREND_SYSTEM_PROMPT = """
You are analyzing performance data from an AI agent system.
Find SYSTEMATIC patterns — not one-off failures.

Focus on:
  - Which query patterns consistently get wrong pattern/skill assignment
  - Which skills are trending downward in quality over recent runs
  - What types of tasks the agent has no skills for (skill gaps)
  - Tool-level failures that affect multiple skills
  - Whether the agent is improving or degrading over time

Output ONLY actionable insights with clear severity.
Ignore noise — only report real systematic issues.
""".strip()


class TrendInsight(BaseModel):
    category: str
    description: str
    action: str
    severity: str  # high | medium | low | positive

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, v: Any) -> str:
        return v.strip().upper() if isinstance(v, str) else str(v)

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, v: Any) -> str:
        return v.strip().lower() if isinstance(v, str) else str(v)


class TrendReport(BaseModel):
    insights: list[TrendInsight]
    overall_health: str  # healthy | stable | degrading | improving

    @field_validator("overall_health", mode="before")
    @classmethod
    def _normalize_health(cls, v: Any) -> str:
        return v.strip().lower() if isinstance(v, str) else str(v)


class TrendDetector:
    """Fires background LLM analysis every N runs to find systematic issues."""

    def __init__(
        self,
        llm: Any,
        feedback_store: FeedbackStore,
        agent_name: str = "Agent",
        run_every: int = TREND_EVERY_N_RUNS,
        llm_timeout: float = 60.0,
        structured_max_retries: int = 2,
    ) -> None:
        self._llm = llm
        self._store = feedback_store
        self._agent = agent_name
        self._run_every = run_every
        self._run_count = 0
        self._last_report: TrendReport | None = None
        self._timeout = llm_timeout
        self._max_retries = structured_max_retries

    def on_run_complete(self) -> None:
        """Increment counter; fire background analysis every N runs."""
        self._run_count += 1
        if self._run_count % self._run_every == 0:
            from ..llm_utils import safe_create_task

            safe_create_task(self._analyze(), name=f"trend-{self._agent}")

    async def force_analyze(self) -> TrendReport | None:
        """Manually trigger analysis (e.g. for testing or dashboards)."""
        return await self._analyze()

    def last_report(self) -> TrendReport | None:
        return self._last_report

    async def _analyze(self) -> TrendReport | None:
        try:
            records = await self._store.get_recent(n=self._run_every)
            if len(records) < MIN_RECORDS_FOR_ANALYSIS:
                logger.debug(
                    f"TrendDetector [{self._agent}]: only {len(records)} records — need {MIN_RECORDS_FOR_ANALYSIS}"
                )
                return None

            stats = self._aggregate(records)
            prompt = self._build_prompt(stats, len(records))

            from ..llm_utils import robust_structured_call

            report = await robust_structured_call(
                self._llm,
                TrendReport,
                [
                    SystemMessage(content=_TREND_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ],
                max_retries=self._max_retries,
                timeout=self._timeout,
                caller=f"TrendDetector[{self._agent}]",
            )
            if report is None:
                logger.warning(f"TrendDetector [{self._agent}]: analysis returned None")
                return None

            self._last_report = report
            self._log_report(report)
            return report

        except Exception as e:
            logger.warning(f"TrendDetector [{self._agent}]: analysis failed: {e}")
            return None

    def _aggregate(self, records: list[dict]) -> dict:
        """Pure-Python aggregation of RunRecord dicts (no LLM)."""
        chron = sorted(records, key=lambda r: str(r.get("created_at") or r.get("rated_at") or ""))
        by_pattern: dict[str, list[float]] = defaultdict(list)
        by_skill: dict[str, list[float]] = defaultdict(list)
        no_skill: int = 0
        total_scores: list[float] = []

        # Chronological split: compare older vs newer runs for drift.
        mid = len(chron) // 2
        first_half_scores: list[float] = []
        second_half_scores: list[float] = []

        for i, r in enumerate(chron):
            score_dict = r.get("score") or {}
            if isinstance(score_dict, dict):
                s = score_dict
                overall = round(
                    (
                        s.get("accuracy", 0.5)
                        + s.get("completeness", 0.5)
                        + s.get("efficiency", 0.5)
                        + s.get("relevance", 0.5)
                    )
                    / 4.0,
                    3,
                )
            else:
                overall = 0.5

            total_scores.append(overall)

            if i < mid:
                first_half_scores.append(overall)
            else:
                second_half_scores.append(overall)

            pattern = r.get("pattern_used", "unknown")
            skill = r.get("skill_used")

            by_pattern[pattern].append(overall)

            if skill:
                by_skill[skill].append(overall)
            else:
                no_skill += 1

        def avg(lst):
            return round(sum(lst) / len(lst), 3) if lst else 0.0

        return {
            "total": len(chron),
            "overall_avg": avg(total_scores),
            "first_half_avg": avg(first_half_scores),
            "second_half_avg": avg(second_half_scores),
            "trend_direction": (
                "improving"
                if avg(second_half_scores) > avg(first_half_scores) + 0.05
                else "degrading"
                if avg(second_half_scores) < avg(first_half_scores) - 0.05
                else "stable"
            ),
            "no_skill_pct": round(no_skill / len(chron) * 100, 1) if chron else 0.0,
            "by_pattern": {p: {"avg": avg(v), "n": len(v)} for p, v in by_pattern.items()},
            "by_skill": {s: {"avg": avg(v), "n": len(v)} for s, v in by_skill.items()},
            # Last 3 runs vs earlier runs (needs ≥6 points); heuristic for per-skill decay.
            "decaying_skills": [s for s, v in by_skill.items() if len(v) >= 6 and avg(v[-3:]) < avg(v[:-3]) - 0.15],
        }

    def _build_prompt(self, stats: dict, n_records: int) -> str:
        pattern_lines = (
            "\n".join(f"  {p}: avg={v['avg']:.2f} n={v['n']}" for p, v in stats["by_pattern"].items()) or "  none"
        )

        skill_lines = (
            "\n".join(f"  {s}: avg={v['avg']:.2f} n={v['n']}" for s, v in stats["by_skill"].items())
            or "  no skills used"
        )

        return f"""
Agent: {self._agent}
Analyzed: {n_records} runs

Overall avg score  : {stats["overall_avg"]:.2f}
First half avg     : {stats["first_half_avg"]:.2f}
Second half avg    : {stats["second_half_avg"]:.2f}
Trend direction    : {stats["trend_direction"]}
Runs with no skill : {stats["no_skill_pct"]}%

Pattern performance:
{pattern_lines}

Skill performance:
{skill_lines}

Decaying skills (recent 3 runs much worse than earlier):
{stats["decaying_skills"] or "none"}
""".strip()

    def _log_report(self, report: TrendReport) -> None:
        logger.info(f"TrendDetector [{self._agent}]: health={report.overall_health} insights={len(report.insights)}")
        for insight in report.insights:
            level = logging.WARNING if insight.severity == "high" else logging.INFO
            logger.log_at(
                level,
                "trend_insight",
                agent=self._agent,
                category=insight.category,
                severity=insight.severity,
                description=insight.description,
                action=insight.action,
            )
