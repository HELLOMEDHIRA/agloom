"""Mandatory post-run scorer that evaluates every agent run on 4 dimensions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from ..models import ExecutionResult
    from .store import FeedbackStore

from ..logging_utils import get_logger

logger = get_logger(__name__)

LOW_SCORE_THRESHOLD = 0.40

_EVAL_SYSTEM_PROMPT = """
You are an objective evaluator of AI agent runs.
Score the run on four dimensions, each 0.0–1.0.
Be strict — 1.0 = perfect, 0.5 = mediocre, 0.0 = completely wrong.

accuracy     : Did the agent answer the query correctly and factually?
completeness : Did it address ALL parts of the query?
efficiency   : Did it use the right pattern and minimum necessary steps?
relevance    : Did it stay on task without irrelevant detours?

IMPORTANT: All four scores MUST be JSON numbers (e.g. 0.9), NOT strings (e.g. "0.9").
Provide one-sentence reasoning for your scores.
""".strip()


class EvalScore(BaseModel):
    accuracy: float = Field(ge=0.0, le=1.0)
    completeness: float = Field(ge=0.0, le=1.0)
    efficiency: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    reasoning: str

    @field_validator("accuracy", "completeness", "efficiency", "relevance", mode="before")
    @classmethod
    def _coerce_float(cls, v: Any) -> float:
        if isinstance(v, str):
            return float(v)
        return v

    def overall(self) -> float:
        return round(
            (self.accuracy + self.completeness + self.efficiency + self.relevance) / 4.0,
            3,
        )

    def to_log_str(self) -> str:
        return (
            f"overall={self.overall():.2f} "
            f"acc={self.accuracy:.1f} "
            f"comp={self.completeness:.1f} "
            f"eff={self.efficiency:.1f} "
            f"rel={self.relevance:.1f}"
        )


class RunRecord(BaseModel):
    """Single run record stored in FeedbackStore.

    ``user_rating`` is application-defined (e.g. positive/negative or numeric scales);
    ``FeedbackStore.apply_user_feedback`` treats a fixed set of strings as negative.

    ``schema_version`` is bumped only when this model shape changes incompatibly
    (external tools may use it for migration).
    """

    schema_version: int = 1
    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_name: str = ""
    query: str
    pattern_used: str = ""
    skill_used: str | None = None
    steps_taken: int = 0
    output_preview: str = ""
    success: bool = True
    score: EvalScore | None = None

    user_id: str | None = None

    user_rating: str | None = None
    user_comment: str | None = None
    user_correction: str | None = None
    rated_at: str | None = None

    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def index_text(self) -> str:
        """Text stored in LTS for semantic search by TrendDetector."""
        score_str = f"score:{self.score.overall():.2f}" if self.score else "score:n/a"
        return f"query:{self.query[:80]} pattern:{self.pattern_used} skill:{self.skill_used or 'none'} {score_str}"


class AutoEvaluator:
    """Fire-and-forget background scorer for every agent run."""

    def __init__(
        self,
        llm: Any,
        feedback_store: FeedbackStore,
        agent_name: str = "Agent",
        llm_timeout: float = 30.0,
        structured_max_retries: int = 2,
        low_score_threshold: float = LOW_SCORE_THRESHOLD,
    ) -> None:
        self._llm = llm
        self._store = feedback_store
        self._agent = agent_name
        self._timeout = llm_timeout
        self._max_retries = structured_max_retries
        self._low_score = low_score_threshold

    def evaluate(
        self,
        result: ExecutionResult,
        query: str,
        skill_used: str | None = None,
    ) -> str:
        """Schedule background evaluation. Returns run_id immediately."""
        run_id = getattr(result, "run_id", None) or uuid.uuid4().hex[:12]
        try:
            object.__setattr__(result, "run_id", run_id)
        except Exception as exc:
            logger.debug(f"AutoEvaluator: could not set run_id on result: {exc!r}")

        from ..llm_utils import safe_create_task

        safe_create_task(
            self._score_and_store(result, query, skill_used, run_id),
            name=f"eval-{run_id}",
        )
        return run_id

    async def _score_and_store(
        self,
        result: ExecutionResult,
        query: str,
        skill_used: str | None,
        run_id: str,
    ) -> None:
        try:
            score = await self._call_llm_eval(result, query)

            uid = (getattr(result, "metadata", None) or {}).get("user_id")

            record = RunRecord(
                run_id=run_id,
                agent_name=self._agent,
                query=query,
                pattern_used=(
                    result.pattern_used.value if hasattr(result, "pattern_used") and result.pattern_used else ""
                ),
                skill_used=skill_used,
                steps_taken=getattr(result, "steps_taken", 0),
                output_preview=str(getattr(result, "output", ""))[:400],
                success=getattr(result, "success", True),
                score=score,
                user_id=str(uid) if uid is not None else None,
            )

            await self._store.save(record)

            if skill_used and score and score.overall() < self._low_score:
                await self._store.signal_skill_failure(skill_used, run_id)
                logger.warning(
                    f"AutoEvaluator [{self._agent}]: low score on "
                    f"skill '{skill_used}' ({score.to_log_str()}) "
                    f"— signalling lifecycle"
                )
            else:
                logger.debug(
                    f"AutoEvaluator [{self._agent}]: run {run_id} {score.to_log_str() if score else 'not scored'}"
                )

        except Exception as e:
            logger.warning(f"AutoEvaluator [{self._agent}]: evaluation failed for run {run_id}: {e}")
            # Store minimal record even on failure — for TrendDetector completeness
            try:
                uid = (getattr(result, "metadata", None) or {}).get("user_id")
                minimal = RunRecord(
                    run_id=run_id,
                    agent_name=self._agent,
                    query=query,
                    skill_used=skill_used,
                    success=getattr(result, "success", False),
                    output_preview=str(getattr(result, "output", "")),
                    user_id=str(uid) if uid is not None else None,
                )
                await self._store.save(minimal)
            except Exception as exc2:
                logger.debug(f"AutoEvaluator: minimal record save also failed: {exc2!r}")

    async def _call_llm_eval(
        self,
        result: ExecutionResult,
        query: str,
    ) -> EvalScore | None:
        output = str(getattr(result, "output", ""))
        if not output.strip():
            return None

        worker_summary = ""
        if hasattr(result, "worker_results") and result.worker_results:
            worker_summary = "\nWorker steps:\n" + "\n".join(
                f"  {r.worker_id}: {str(r.task)[:60]} → {r.signal.value}" for r in result.worker_results
            )

        prompt = f"""
Agent query  : {query}
Pattern used : {result.pattern_used.value if hasattr(result, "pattern_used") and result.pattern_used else "unknown"}
Steps taken  : {getattr(result, "steps_taken", 0)}
Run success  : {getattr(result, "success", True)}
Output       :
{output[:600]}
{worker_summary}
""".strip()

        from ..llm_utils import robust_structured_call

        return await robust_structured_call(
            self._llm,
            EvalScore,
            [
                SystemMessage(content=_EVAL_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ],
            max_retries=self._max_retries,
            timeout=self._timeout,
            caller=f"AutoEvaluator[{self._agent}]",
        )
