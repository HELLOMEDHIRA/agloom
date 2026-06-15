"""Shared Pydantic types: patterns, analysis, execution results, worker plans, agent config validation."""

from __future__ import annotations

import logging as _logging
import re as _re
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .logging_utils import get_logger

_cfg_logger = get_logger(__name__)

from agloom.prompts.core import DEFAULT_SYSTEM_PROMPT  # noqa: F401 — public re-export


class SignalType(str, Enum):
    """
    Level 4 signals emitted into agent["signal_queue"].
    HALT_ALL              → cancel all running worker tasks immediately
    CLARIFICATION_REQUEST → worker needs human input before continuing
    SUCCESS               → worker completed normally
    FAILED                → worker failed after retries
    HALTED                → user HALT_ALL or cooperative stop (not a retryable failure)
    """

    HALT_ALL = "HALT_ALL"
    CLARIFICATION_REQUEST = "CLARIFICATION_REQUEST"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    HALTED = "HALTED"


class Signal(BaseModel):
    """
    Inter-agent signal passed via the signal_queue.

    response_queue is typed as Any (not asyncio.Queue) so models.py stays
    import-free of asyncio and Pydantic skips serialisation of the runtime
    object.  Present only for CLARIFICATION_REQUEST — the signal listener
    puts the human's answer here to unblock the waiting worker.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    signal_type: SignalType
    worker_id: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    response_queue: Any | None = None


class PatternType(str, Enum):
    """
    9 canonical execution patterns.

    agloom execution engine (create → DAG → destroy) underlies
    all patterns involving workers (SUPERVISOR through HYBRID_DAG).

    Complexity routing:
      0–2  → DIRECT           inline answer, 0 tool calls
      3–4  → REACT            single agent + tool loop
      5–6  → SUPERVISOR       all workers parallel + manager aggregates
      5–6  → PIPELINE         fixed linear A→B→C transform chain
      6–7  → PLANNER_EXECUTOR all sequential, each step feeds the next
      7–8  → REFLECTION       generate → critique → refine loop
      7–9  → SWARM            peer-to-peer, no central manager
      8–10 → BLACKBOARD       shared evolving state, reactive coordination
      8–10 → HYBRID_DAG       mixed parallel + sequential DAG

    Cross-cutting (handled via config — NOT patterns):
      HITL       → interrupt_before / interrupt_after + user_callback
      Guardrail  → AgentMiddleware.before_agent()
      Validation → AgentMiddleware.after_agent()
      Routing    → analyze_query() in classifier.py
    """

    DIRECT = "DIRECT"
    REACT = "REACT"
    SUPERVISOR = "SUPERVISOR"
    PIPELINE = "PIPELINE"
    PLANNER_EXECUTOR = "PLANNER_EXECUTOR"
    REFLECTION = "REFLECTION"
    SWARM = "SWARM"
    BLACKBOARD = "BLACKBOARD"
    HYBRID_DAG = "HYBRID_DAG"


class SubTask(BaseModel):
    """
    A single subtask planned by the Manager / Classifier LLM.
    Produced inside QueryAnalysis.subtasks for multi-worker patterns.

    context is dict[str, str] — flat key/value pairs ONLY.
    The LLM sometimes generates nested structures or lists inside context
    (e.g. {"facts": ["name": "Priya"...]}) which breaks strict tool JSON.
    The validator below flattens any non-str value to its string repr so
    malformed planner output still round-trips through tool-calling APIs.
    """

    worker_id: str
    task: str
    required_tools: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    system_instruction: str = ""
    context: dict[str, str] = Field(default_factory=dict)

    @field_validator("required_tools", "depends_on", mode="before")
    @classmethod
    def _coerce_list(cls, v: Any) -> list[str]:
        """LLMs sometimes emit '[]' or '["a"]' as a string instead of a real JSON array."""
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

    @field_validator("context", mode="before")
    @classmethod
    def _flatten_context(cls, v: Any) -> dict[str, str]:
        """
        Sanitize LLM-generated context to flat dict[str, str].
        Handles: nested dicts, lists, non-dict entirely → {}
        """
        if not isinstance(v, dict):
            return {}
        return {str(k): val if isinstance(val, str) else str(val) for k, val in v.items()}


class QueryAnalysis(BaseModel):
    """Output of analyze_query() — classifier's full reasoning."""

    pattern: PatternType
    complexity: int = Field(ge=0, le=10)
    reasoning: str
    direct_response: str | None = None
    can_parallelize: bool = False
    needs_reflection: bool = False
    estimated_steps: int = Field(default=1, ge=1)
    subtasks: list[SubTask] = Field(default_factory=list)
    matched_skill: str | None = None
    orchestration_depth: int | None = Field(
        default=None,
        ge=0,
        le=20,
        description="Suggested max recursive pattern depth for this turn (clamped to agent ceiling).",
    )
    orchestration_token_budget: int | None = Field(
        default=None,
        ge=0,
        description="Suggested orchestration token budget for this turn.",
    )
    orchestration_llm_call_budget: int | None = Field(
        default=None,
        ge=0,
        description="Suggested max orchestration LLM calls for this turn.",
    )
    orchestration_auto_escalation: bool | None = Field(
        default=None,
        description="Suggested auto-escalation for this turn (requires agent enable_auto_escalation).",
    )

    @field_validator("complexity", "estimated_steps", mode="before")
    @classmethod
    def _coerce_int_fields(cls, v: Any) -> Any:
        """Structured tool output often sends ints as strings; normalize here."""
        if v is None:
            return v
        if isinstance(v, bool):
            raise ValueError("boolean is not a valid integer for this field")
        if isinstance(v, int):
            return v
        if isinstance(v, float) and v == int(v):
            return int(v)
        if isinstance(v, str):
            s = v.strip()
            if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
                return int(s)
            try:
                f = float(s)
                if f == int(f):
                    return int(f)
            except ValueError:
                pass
        return v


# Common truthy/falsy spellings from LLM tool JSON (only "true"/"false" is schema-safe).
_WIRE_BOOL_TRUE = frozenset({"true", "1", "yes", "y", "on"})
_WIRE_BOOL_FALSE = frozenset({"false", "0", "no", "n", "off"})


def parse_wire_bool(value: Any) -> bool:
    """Interpret classifier / tool boolean wire values (bool, number, or string)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, int | float):
        return value != 0
    s = str(value).strip().lower()
    if s in ("", "null", "none", "undefined"):
        return False
    if s in _WIRE_BOOL_TRUE:
        return True
    if s in _WIRE_BOOL_FALSE:
        return False
    try:
        return int(float(s)) != 0
    except ValueError:
        return False


class QueryAnalysisToolPayload(BaseModel):
    """
    Wire format for classifier structured output / tool calls (any chat provider).

    Tool-calling endpoints validate arguments against JSON Schema before your
    code runs; models often emit strings for numeric and boolean fields. This
    model matches that reality on the wire. ``query_analysis_from_tool_payload``
    converts to strict ``QueryAnalysis`` for internal use (graph state, patterns).
    """

    pattern: str
    complexity: str = "5"
    reasoning: str = ""
    direct_response: str | None = None
    can_parallelize: str = "false"
    needs_reflection: str = "false"
    estimated_steps: str = "1"
    subtasks: list[SubTask] = Field(default_factory=list)
    matched_skill: str | None = None
    orchestration_depth: str = ""
    orchestration_token_budget: str = ""
    orchestration_llm_call_budget: str = ""
    orchestration_auto_escalation: str = ""

    @field_validator("direct_response", mode="before")
    @classmethod
    def _nullish_direct(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str) and v.strip().lower() in ("", "null", "none", "undefined"):
            return None
        return v

    @field_validator(
        "orchestration_depth",
        "orchestration_token_budget",
        "orchestration_llm_call_budget",
        mode="before",
    )
    @classmethod
    def _optional_int_wire(cls, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return ""
        if isinstance(v, int | float):
            return str(max(0, int(v)))
        s = str(v).strip()
        if s.lower() in ("", "null", "none", "undefined", "n/a"):
            return ""
        return s

    @field_validator("orchestration_auto_escalation", mode="before")
    @classmethod
    def _optional_bool_wire(cls, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return "true" if v else "false"
        s = str(v).strip().lower()
        if s in ("", "null", "none", "undefined", "n/a"):
            return ""
        return "true" if parse_wire_bool(v) else "false"

    @field_validator("complexity", mode="before")
    @classmethod
    def _complexity_wire(cls, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return "5"
        if isinstance(v, int | float):
            return str(int(v))
        return str(v).strip()

    @field_validator("estimated_steps", mode="before")
    @classmethod
    def _steps_wire(cls, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return "1"
        if isinstance(v, int | float):
            return str(int(v))
        return str(v).strip()

    @field_validator("can_parallelize", "needs_reflection", mode="before")
    @classmethod
    def _bool_wire(cls, v: Any) -> str:
        return "true" if parse_wire_bool(v) else "false"


def query_analysis_from_tool_payload(
    raw: QueryAnalysisToolPayload,
    tools_available: bool = False,
) -> QueryAnalysis:
    """
    Map the permissive wire model → strict QueryAnalysis.

    Enforces pattern-field invariants that LLMs occasionally violate:
      REFLECTION → needs_reflection is forced True
      DIRECT     → direct_response fallback guaranteed non-empty
    """
    try:
        pattern = PatternType(raw.pattern.upper())
    except (ValueError, AttributeError):
        pattern = PatternType.REACT if tools_available else PatternType.DIRECT

    try:
        complexity = max(0, min(10, int(raw.complexity)))
    except (ValueError, TypeError):
        complexity = 5

    try:
        estimated_steps = max(1, int(raw.estimated_steps))
    except (ValueError, TypeError):
        estimated_steps = 1

    can_parallelize = parse_wire_bool(raw.can_parallelize)

    # REFLECTION pattern without needs_reflection=True silently skips
    # the critique loop in patterns/reflection.py — enforce the invariant.
    _needs_reflection = parse_wire_bool(raw.needs_reflection)
    needs_reflection = True if pattern == PatternType.REFLECTION else _needs_reflection

    reasoning = raw.reasoning or f"Routed to {pattern.value} pattern."

    direct_response = raw.direct_response if pattern == PatternType.DIRECT else None

    subtasks = raw.subtasks if isinstance(raw.subtasks, list) else []

    matched_skill = getattr(raw, "matched_skill", None)
    if matched_skill and isinstance(matched_skill, str):
        matched_skill = matched_skill.strip() or None

    def _optional_wire_int(field: str) -> int | None:
        raw_val = getattr(raw, field, "") or ""
        s = str(raw_val).strip()
        if not s or s.lower() in ("null", "none", "undefined", "n/a"):
            return None
        try:
            return max(0, int(s))
        except ValueError:
            return None

    esc_raw = getattr(raw, "orchestration_auto_escalation", "") or ""
    esc_s = str(esc_raw).strip().lower()
    if not esc_s or esc_s in ("null", "none", "undefined", "n/a"):
        orchestration_auto_escalation = None
    else:
        orchestration_auto_escalation = parse_wire_bool(esc_raw)

    return QueryAnalysis(
        pattern=pattern,
        complexity=complexity,
        reasoning=reasoning,
        direct_response=direct_response,
        subtasks=subtasks,
        estimated_steps=estimated_steps,
        can_parallelize=can_parallelize,
        needs_reflection=needs_reflection,
        matched_skill=matched_skill,
        orchestration_depth=_optional_wire_int("orchestration_depth"),
        orchestration_token_budget=_optional_wire_int("orchestration_token_budget"),
        orchestration_llm_call_budget=_optional_wire_int("orchestration_llm_call_budget"),
        orchestration_auto_escalation=orchestration_auto_escalation,
    )


REFLECTION_GOAL_WORKER_ID = "goal"


def normalize_reflection_analysis(analysis: QueryAnalysis, query: str) -> QueryAnalysis:
    """Ensure REFLECTION has a goal subtask when the classifier omitted ``subtasks``.

    The classifier contract requires exactly one subtask for REFLECTION; models
    sometimes return pattern=REFLECTION with an empty list. Synthesizing the goal
    from the user query matches supervisor-style resilience and avoids a hard fail.
    """
    if analysis.pattern != PatternType.REFLECTION or analysis.subtasks:
        return analysis
    task = (query or "").strip()
    if not task:
        return analysis
    return analysis.model_copy(
        update={
            "subtasks": [
                SubTask(
                    worker_id=REFLECTION_GOAL_WORKER_ID,
                    task=task,
                    system_instruction="",
                    required_tools=[],
                )
            ],
        }
    )


class WorkerPlan(BaseModel):
    """
    Resolved worker plan before tool injection.
    Built from SubTask — same fields, explicit typing.

    context uses the same dict[str, str] constraint as SubTask.
    """

    worker_id: str
    task: str
    system_instruction: str = ""
    required_tools: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    context: dict[str, str] = Field(default_factory=dict)

    @field_validator("required_tools", "depends_on", mode="before")
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

    @field_validator("context", mode="before")
    @classmethod
    def _flatten_context(cls, v: Any) -> dict[str, str]:
        """Same flattening as SubTask — see SubTask._flatten_context."""
        if not isinstance(v, dict):
            return {}
        return {str(k): val if isinstance(val, str) else str(val) for k, val in v.items()}


class ResolvedWorkerConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    worker_id: str
    task: str
    system_prompt: str
    tools: list[Any] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    llm_timeout: float = 120.0
    max_retries: int = 2
    retry_delay: float = 1.0
    interrupt_before_tools: list[str] = Field(default_factory=list)
    user_callback: Any | None = Field(default=None, exclude=True)
    missing_tools: list[str] = Field(default_factory=list)


class WorkerResult(BaseModel):
    """Output of run_worker() — one per worker."""

    worker_id: str
    task: str
    output: str
    signal: SignalType = SignalType.SUCCESS
    error: str | None = None
    elapsed_ms: float = 0.0
    attempt: int = 1  # 1-based: which attempt produced this result
    token_usage: dict[str, int] = Field(default_factory=dict)
    steps: list[Any] = Field(default_factory=list)
    messages: list[Any] = Field(default_factory=list)


class StepType(str, Enum):
    """Types of steps captured in the execution trace."""

    CLASSIFY = "classify"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    WORKER_START = "worker_start"
    WORKER_END = "worker_end"
    CACHE_HIT = "cache_hit"
    REFLECTION = "reflection"
    FALLBACK = "fallback"
    INTERRUPT = "interrupt"
    TOKEN = "token"  # noqa: S105 — StepType enum value (stream chunk), not a credential


class AgentStep(BaseModel):
    """A single step in the agent execution trace."""

    type: StepType
    name: str
    input: str = ""
    output: str = ""
    duration_ms: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentEvent(BaseModel):
    """Live event emitted during execution for UI streaming."""

    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ExecutionResult(BaseModel):
    """
    Final output of run_agent() / UnifiedAgent.ainvoke().

    interrupts:
      Raw Interrupt objects from LangGraph state["__interrupt__"] when
      a graph node calls interrupt(). Callers inspect interrupts[0].value
      to surface the question that caused the pause. Empty list when run
      completes normally.
    analysis:
      Classifier output for this turn (pattern, complexity, subtasks). Also persisted
      in LangGraph checkpoints when a checkpointer is configured.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    pattern_used: PatternType
    query: Any
    output: str
    steps_taken: int = 0
    success: bool = True
    analysis: QueryAnalysis | None = Field(
        default=None,
        description="Classifier output for this turn; persisted in checkpoints when configured.",
    )
    worker_results: list[Any] = Field(default_factory=list)
    error: str | None = None
    thread_id: str | None = None
    run_id: str = ""
    interrupts: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    steps: list[AgentStep] = Field(default_factory=list)
    token_usage: dict[str, int] = Field(default_factory=dict)
    messages: list[Any] = Field(
        default_factory=list,
        description="Raw LangChain message objects (AIMessage, HumanMessage, ToolMessage, etc.) from the execution.",
    )

    def model_post_init(self, __context: Any) -> None:
        if not self.success and not self.error and self.output:
            object.__setattr__(self, "error", self.output[:500])


class OrchestrationBudgetExceeded(Exception):
    """Raised when depth, token, or LLM-call budgets are exceeded."""


class OrchestrationCycleDetected(Exception):
    """Raised when recursive cycle detection fires."""


class PatternEscalationError(Exception):
    """Raised when escalation rules cannot resolve a situation."""


class SpawnInstruction(BaseModel):
    """Instruction to run a pattern (root query or spawned sub-pattern)."""

    pattern: PatternType
    task: str
    system_instruction: str = ""
    required_tools: list[str] = Field(default_factory=list)
    context: dict[str, str] = Field(default_factory=dict)
    parent_worker_id: str = ""
    escalation_reason: str = ""
    max_depth: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    reclassify: bool = False


class OrchestrationStep(BaseModel):
    """One step in the orchestration trace."""

    depth: int
    pattern: PatternType
    worker_id: str = ""
    action: str
    input_preview: str = ""
    output_preview: str = ""
    reason: str = ""
    duration_ms: float = 0.0
    token_usage: dict[str, int] = Field(default_factory=dict)
    error: str | None = None
    confidence: float | None = None
    quality_score: float | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class SpawnedPatternRecord(BaseModel):
    """Record of a spawned sub-pattern for cycle detection."""

    spawn_id: str
    pattern: PatternType
    task_hash: str
    worker_id: str = ""
    parent_pattern: PatternType | None = None
    reason: str = ""
    depth: int = 0
    success: bool | None = None
    output_preview: str = ""


class FailureRecord(BaseModel):
    worker_id: str = ""
    pattern: PatternType
    error: str
    depth: int = 0
    attempt: int = 0


class RetryRecord(BaseModel):
    worker_id: str = ""
    pattern: PatternType
    attempt: int = 0
    reason: str = ""
    max_attempts: int = 0


class OrchestrationContext(BaseModel):
    """Shared state across recursive pattern invocations."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    current_depth: int = 0
    max_depth: int = 5
    root_query: str = ""
    agent_config: dict[str, Any] = Field(default_factory=dict)

    active_pattern: PatternType | None = None
    parent_pattern: PatternType | None = None
    parent_worker_id: str | None = None
    grandparent_pattern: PatternType | None = None

    orchestration_trace: list[OrchestrationStep] = Field(default_factory=list)
    spawned_history: list[SpawnedPatternRecord] = Field(default_factory=list)

    total_tokens_used: int = 0
    max_total_tokens: int = 0
    total_llm_calls: int = 0
    max_total_llm_calls: int = 100
    auto_escalation: bool = False
    turn_plan_source: str = ""

    confidence_scores: list[float] = Field(default_factory=list)
    quality_scores: list[float] = Field(default_factory=list)
    failure_history: list[FailureRecord] = Field(default_factory=list)
    retry_history: list[RetryRecord] = Field(default_factory=list)
    shared_results: dict[str, Any] = Field(default_factory=dict)

    event_queue: Any = Field(default=None, exclude=True)

    def child_context(
        self,
        *,
        active_pattern: PatternType,
        worker_id: str = "",
    ) -> OrchestrationContext:
        """Context for a spawned child pattern (depth +1)."""
        return self.model_copy(
            update={
                "current_depth": self.current_depth + 1,
                "grandparent_pattern": self.parent_pattern,
                "parent_pattern": self.active_pattern,
                "active_pattern": active_pattern,
                "parent_worker_id": worker_id or self.parent_worker_id,
                "orchestration_trace": list(self.orchestration_trace),
                "spawned_history": list(self.spawned_history),
                "confidence_scores": list(self.confidence_scores),
                "quality_scores": list(self.quality_scores),
                "failure_history": list(self.failure_history),
                "retry_history": list(self.retry_history),
                "shared_results": dict(self.shared_results),
                "auto_escalation": self.auto_escalation,
                "turn_plan_source": self.turn_plan_source,
            }
        )

    def check_budget(self, *, depth_override: int | None = None) -> None:
        depth = self.current_depth if depth_override is None else depth_override
        if self.max_depth > 0 and depth >= self.max_depth:
            raise OrchestrationBudgetExceeded(f"Max depth {self.max_depth} reached at depth {depth}")
        if self.max_total_llm_calls > 0 and self.total_llm_calls >= self.max_total_llm_calls:
            raise OrchestrationBudgetExceeded(f"Max LLM calls {self.max_total_llm_calls} reached")
        if self.max_total_tokens > 0 and self.total_tokens_used >= self.max_total_tokens:
            raise OrchestrationBudgetExceeded(f"Max tokens {self.max_total_tokens} reached")


DEFAULT_STEP_MAX_LENGTH: int = 0  # 0 or negative: no truncation in _trunc/_make_step


def _trunc(s: str, limit: int = DEFAULT_STEP_MAX_LENGTH) -> str:
    """Truncate string to *limit* characters.

    *limit* ≤ 0 means **no limit** (full string). The default is 0 so call sites
    that omit ``max_length`` do not truncate unless they pass a positive cap.
    """
    if limit <= 0:
        return s
    return s[:limit]


def _make_step(
    step_type: StepType,
    name: str,
    *,
    input: str = "",
    output: str = "",
    duration_ms: float = 0.0,
    max_length: int = DEFAULT_STEP_MAX_LENGTH,
    **extra: Any,
) -> AgentStep:
    """Convenience factory for AgentStep with auto-timestamp."""
    return AgentStep(
        type=step_type,
        name=name,
        input=_trunc(input, max_length),
        output=_trunc(output, max_length),
        duration_ms=duration_ms,
        metadata=extra,
    )


def _merge_token_usage(base: dict[str, int], addition: dict[str, int]) -> dict[str, int]:
    """Merge token usage dicts by summing values."""
    merged = dict(base)
    for k, v in addition.items():
        merged[k] = merged.get(k, 0) + v
    return merged


def _merge_token_usage_max_per_key(base: dict[str, int], addition: dict[str, int]) -> dict[str, int]:
    """Merge usage by taking the max per key (cumulative totals repeated on multiple AIMessages)."""
    if not addition:
        return dict(base)
    if not base:
        return dict(addition)
    keys = set(base) | set(addition)
    return {k: max(base.get(k, 0), addition.get(k, 0)) for k in keys}


def _canonical_token_usage(usage: dict[str, int]) -> dict[str, int]:
    """Map provider-specific keys (``prompt_tokens``, ``completion_tokens``, …) to input/output."""
    inp = (usage.get("input_tokens", 0) or 0) + (usage.get("prompt_tokens", 0) or 0)
    out = (usage.get("output_tokens", 0) or 0) + (usage.get("completion_tokens", 0) or 0)
    canonical: dict[str, int] = {}
    if inp:
        canonical["input_tokens"] = inp
    if out:
        canonical["output_tokens"] = out
    raw_total = usage.get("total_tokens")
    if isinstance(raw_total, int) and raw_total > 0:
        canonical["total_tokens"] = raw_total
    elif inp and out and ("prompt_tokens" in usage or "completion_tokens" in usage):
        canonical["total_tokens"] = inp + out
    return canonical


def _usage_from_metadata(meta: Any) -> dict[str, int]:
    """Normalize LangChain ``usage_metadata`` (dict or object) to int fields."""
    usage: dict[str, int] = {}
    if not meta:
        return usage
    if isinstance(meta, dict):
        for k, v in meta.items():
            if isinstance(v, int):
                usage[k] = v
            elif v is not None:
                try:
                    usage[k] = int(v)
                except (TypeError, ValueError):
                    continue
        return _canonical_token_usage(usage)
    for field in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
    ):
        val = getattr(meta, field, None)
        if val is not None:
            try:
                usage[field] = int(val)
            except (TypeError, ValueError):
                continue
    return _canonical_token_usage(usage)


def _extract_token_usage(response: Any) -> dict[str, int]:
    """Extract token usage from a LangChain AIMessage or response dict.

    When *messages* lists multiple assistant turns with ``usage_metadata``, values are
    merged by **summing** per key (OpenAI-style per-call totals). Streaming accumulation
    uses :func:`agloom.wire_tokens.accumulate_stream_usage` (monotonic max per chunk).
    """
    usage: dict[str, int] = {}
    messages = None
    if isinstance(response, dict):
        messages = response.get("messages", [])
    elif hasattr(response, "messages"):
        messages = response.messages
    if messages:
        for msg in messages:
            meta = getattr(msg, "usage_metadata", None)
            if meta:
                usage = _merge_token_usage(usage, _usage_from_metadata(meta))
        if usage:
            return usage
    if not usage and isinstance(response, dict):
        meta = response.get("usage_metadata")
        if meta:
            usage = _usage_from_metadata(meta)
    if not usage and hasattr(response, "usage_metadata") and response.usage_metadata:
        usage = _usage_from_metadata(response.usage_metadata)
    return usage


_VALID_PATTERN_VALUES: frozenset[str] = frozenset(p.value.upper() for p in PatternType)


_model_logger = _logging.getLogger("agloom.models")

_PROVIDER_PREFIXED = _re.compile(r"^[a-z_-]+:")
_HAS_SLASH = _re.compile(r"/")

_KNOWN_BARE_PREFIXES = (
    "gpt-",
    "o1-",
    "o3-",
    "o4-",
    "claude-",
    "gemini-",
    "gemma-",
    "llama-",
    "mistral-",
    "mixtral-",
    "codestral-",
    "deepseek-",
    "command-",
    "qwen",
)

_PROVIDER_HINTS: dict[str, str] = {
    "gpt-": "openai",
    "o1-": "openai",
    "o3-": "openai",
    "o4-": "openai",
    "claude-": "anthropic",
    "gemini-": "google_genai",
    "gemma-": "google_genai",
    "command-": "cohere",
    "llama-": "groq",
    "mistral-": "mistralai",
    "mixtral-": "groq",
    "codestral-": "mistralai",
    "deepseek-": "deepseek",
    "qwen": "together",
}


def _validate_model_string(model_id: str) -> None:
    """Warn if a model-id string looks like a bare model name without a provider.

    Does NOT raise — only emits a warning so developers catch typos early
    instead of getting a cryptic error on the first LLM call.
    """
    if _PROVIDER_PREFIXED.match(model_id) or _HAS_SLASH.search(model_id):
        return

    lower = model_id.lower()
    for prefix in _KNOWN_BARE_PREFIXES:
        if lower.startswith(prefix):
            hint = _PROVIDER_HINTS.get(prefix, "")
            suggestion = f"'{hint}:{model_id}'" if hint else f"'provider:{model_id}' or 'org/{model_id}'"
            _model_logger.warning(
                f"Model string '{model_id}' looks like a bare model name without a provider prefix. "
                f"This may fail at runtime. Did you mean {suggestion}? "
                f"Examples: 'openai:gpt-4o', 'anthropic:claude-3-5-sonnet', 'meta-llama/llama-4-scout-17b-16e-instruct'."
            )
            return

    _model_logger.warning(
        f"Model string '{model_id}' has no provider prefix (e.g. 'openai:') or org slash (e.g. 'meta-llama/'). "
        f"If this is intentional (e.g. a custom endpoint), you can ignore this warning. "
        f"Otherwise, use 'provider:model-name' format."
    )


def _validate_model_object(model: Any) -> None:
    """Warn if a model object doesn't look like a valid LLM."""
    if not (hasattr(model, "ainvoke") or hasattr(model, "invoke")):
        _model_logger.warning(
            f"Model object of type '{type(model).__name__}' has no 'ainvoke' or 'invoke' method. "
            f"Expected a BaseChatModel instance (e.g. ChatGroq, ChatOpenAI). "
            f"This will likely fail at runtime."
        )


class AgentConfig(BaseModel):
    """
    Validated input schema for the core kwargs shared with create_agent().

    Usage (inside create_agent only — callers never instantiate this directly):
        cfg = AgentConfig(model=model, tools=tools, name=name, ...)

    Construction raises ValueError on invalid arguments. Fields mirror the
    subset of create_agent() parameters validated here (interrupt lists, MCP,
    timeouts, memory/store wiring, etc.). Additional factory-only parameters —
    for example ``delegates``, ``feedback_handler``, ``frozen``,
    ``harness``, ``max_step_output_length``, ``fallback_pattern`` — are checked
    or applied in ``unified_agent.create_agent`` after this model runs.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: Any  # BaseChatModel or non-empty model-id str; Any keeps this module free of langchain imports
    name: str = "UnifiedAgent"

    tools: list[Any] = Field(default_factory=list)
    system_prompt: Any = None

    middleware: list[Any] = Field(default_factory=list)
    response_format: Any = None
    state_schema: Any = None
    context_schema: Any = None
    checkpointer: Any = None
    store: Any = None

    memory: Any = None  # SessionMemory | None
    enable_memory_tools: bool = True
    query_cache: Any = None

    interrupt_before: list[str] = Field(default_factory=list)
    interrupt_after: list[str] = Field(default_factory=list)
    interrupt_before_tools: list[str] = Field(default_factory=list)
    interrupt_before_workers: list[str] = Field(default_factory=list)
    interrupt_after_workers: list[str] = Field(default_factory=list)
    user_callback: Any = Field(
        default=None,
        description="Human-in-the-loop decisions: event names and semantics in ``agloom.hitl_contract`` (``HITLEvent``).",
    )

    debug: bool = False
    max_concurrent: int = Field(default=4, ge=1, le=32)
    max_retries: int = Field(default=2, ge=0, le=10)
    retry_delay: float = Field(default=1.0, ge=0.0)

    llm_timeout: float = Field(
        default=120.0, ge=1.0, description="Default timeout (s) for non-structured LLM ainvoke calls"
    )
    react_graph_timeout: float | None = Field(
        default=None,
        ge=1.0,
        description=(
            "Wall clock (s) for streamed REACT graphs (astream_events). "
            "Default max(llm_timeout×4, 300) when None."
        ),
    )
    classifier_timeout: float = Field(
        default=60.0, ge=1.0, description="Timeout (s) for the classifier structured call"
    )
    structured_max_retries: int = Field(
        default=2, ge=0, le=10, description="Max retries inside robust_structured_call()"
    )

    rate_limit: float | None = Field(default=None, description="Max LLM calls/sec (None=unlimited)")

    low_score_threshold: float = Field(
        default=0.40, ge=0.0, le=1.0, description="Auto-evaluator threshold below which skill failure is signalled"
    )
    review_every_n_runs: int = Field(default=25, ge=1, description="Skill lifecycle review fires every N runs")
    trend_every_n_runs: int = Field(default=100, ge=1, description="Trend detector analysis fires every N runs")
    max_skills: int = Field(default=30, ge=1, description="Max active skills before forced review")

    user_id: str | None = None
    session_max_turns: int = Field(default=50, ge=1)
    max_reflection_iterations: int = Field(default=3, ge=1)
    reflection_threshold: int = Field(default=7, ge=0, le=10)

    auto_summarize: bool = Field(default=True, description="Enable auto-summarization of conversation history")
    summarize_threshold: int = Field(
        default=200_000, ge=10_000, description="Token count threshold that triggers auto-summarization"
    )
    summarize_max_tokens_budget: int | None = Field(
        default=None,
        description=(
            "When set (or inferred from the chat model's max_tokens), rolling memory summarizes "
            "when estimated stored tokens exceed 80% of this budget; otherwise summarize_threshold applies."
        ),
    )
    summarizer_model: Any = None

    mcp_servers: list[Any] = Field(default_factory=list)

    react_force_tool_choice_on_user_turn: bool = Field(
        default=True,
        description=(
            "Opening turn: tool_choice=required for Groq-style providers. Qwen3/vLLM/LiteLLM: "
            "no tool_choice override (provider default). User blocks flattened via LLM wrapper "
            "(always). False disables tool_choice overrides only."
        ),
    )

    react_tool_use_failed_auto_retries_hitl: int = Field(
        default=2,
        ge=0,
        le=5,
        description=(
            "ReAct + L2 HITL: silent tool_use_failed retries before the user_callback receives "
            "REACT_TOOL_USE_FAILED. See ``agloom.hitl_contract``."
        ),
    )
    react_tool_use_failed_user_rounds: int = Field(
        default=3,
        ge=0,
        le=20,
        description=(
            "ReAct: how many times the user_callback may extend the run with a user-chosen "
            "retry after REACT_TOOL_USE_FAILED. See ``agloom.hitl_contract``."
        ),
    )

    max_pattern_depth: int = Field(
        default=0,
        ge=0,
        le=20,
        description=(
            "Ceiling for recursive pattern depth (0 = orchestration off). "
            "When orchestration_plan_from_classifier is True, the classifier picks a per-turn depth ≤ this value."
        ),
    )
    orchestration_plan_from_classifier: bool = Field(
        default=True,
        description=(
            "When True and max_pattern_depth > 0, analyze_query() sets per-turn depth, token/LLM budgets, "
            "and escalation (clamped to agent ceilings). When False, agent ceilings apply directly."
        ),
    )
    max_orchestration_llm_calls: int = Field(
        default=100,
        ge=0,
        description="Max total LLM calls across orchestration spawns (0 = unlimited).",
    )
    max_orchestration_tokens: int = Field(
        default=0,
        ge=0,
        description="Max total tokens across orchestration spawns (0 = unlimited).",
    )
    enable_auto_escalation: bool = Field(
        default=False,
        description="When True, post-execution evaluation may spawn follow-up patterns.",
    )
    escalation_rules: list[str] = Field(
        default_factory=lambda: ["default"],
        description="Escalation rule set: 'default', 'conservative', or 'aggressive'.",
    )
    enable_pattern_spawns: bool = Field(
        default=True,
        description="When orchestration is on, pattern handlers may spawn sub-patterns.",
    )
    enable_orchestration_llm_eval: bool = Field(
        default=True,
        description=(
            "Use an LLM call for orchestration quality and conflict evaluation on each dispatch step. "
            "Set False for minimal structural fallback only."
        ),
    )
    enable_dynamic_dag_nodes: bool = Field(
        default=True,
        description="HYBRID_DAG nodes reclassify and dispatch sub-patterns when orchestration is on.",
    )
    enable_supervisor_worker_dispatch: bool = Field(
        default=True,
        description="SUPERVISOR workers use per-worker dispatch when orchestration is on (no worker HITL).",
    )
    orchestration_evaluation_llm: Any = Field(
        default=None,
        description="Optional separate LLM for orchestration evaluation (defaults to main model).",
    )

    @field_validator("rate_limit")
    @classmethod
    def rate_limit_must_be_positive(cls, v: float | None) -> float | None:
        if v is not None and v < 0.1:
            raise ValueError(f"rate_limit must be >= 0.1, got {v}")
        return v

    @field_validator("model")
    @classmethod
    def model_must_be_set(cls, v: Any) -> Any:
        if v is None:
            raise ValueError(
                "model is required. Pass a BaseChatModel instance or a model-id string "
                "(e.g. 'openai:gpt-4o', 'anthropic:claude-3-5-sonnet-20241022')."
            )
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("model string is empty. Pass a non-empty model-id (e.g. 'openai:gpt-4o').")
            _validate_model_string(v)
        else:
            _validate_model_object(v)
        return v

    @field_validator("name")
    @classmethod
    def name_must_be_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("name must be a non-empty string. It appears in every log line — make it meaningful.")
        return v.strip()

    @field_validator("interrupt_before", "interrupt_after", mode="before")
    @classmethod
    def validate_pattern_list(cls, v: Any) -> list[str]:
        if v is None:
            return []
        normalised = [s.upper() for s in v]
        invalid = [s for s in normalised if s not in _VALID_PATTERN_VALUES]
        if invalid:
            valid_sorted = sorted(_VALID_PATTERN_VALUES)
            raise ValueError(f"Unknown pattern(s) in interrupt list: {invalid}. Valid values: {valid_sorted}")
        return normalised

    @field_validator("user_callback")
    @classmethod
    def callback_must_be_callable(cls, v: Any) -> Any:
        if v is not None and not callable(v):
            raise ValueError(f"user_callback must be a callable (async def or def), got {type(v).__name__!r}.")
        return v

    @field_validator("tools", mode="before")
    @classmethod
    def tools_none_to_empty(cls, v: Any) -> list:
        return list(v) if v is not None else []

    @field_validator("middleware", mode="before")
    @classmethod
    def middleware_none_to_empty(cls, v: Any) -> list:
        return list(v) if v is not None else []

    @field_validator("mcp_servers", mode="before")
    @classmethod
    def mcp_servers_none_to_empty(cls, v: Any) -> list:
        return list(v) if v is not None else []

    @model_validator(mode="after")
    def warn_interrupt_without_callback(self) -> AgentConfig:
        """
        HITL interrupt lists without a user_callback are a silent no-op.
        The gate fires but always returns True (fail-open) because there is
        nobody to ask. Emit a warning so the caller knows immediately.

        This is a WARNING not an error — callers may attach the callback
        after construction via agent.config["user_callback"] = cb.
        """
        has_interrupt = any(
            [
                self.interrupt_before,
                self.interrupt_after,
                self.interrupt_before_tools,
                self.interrupt_before_workers,
                self.interrupt_after_workers,
            ]
        )
        if has_interrupt and self.user_callback is None:
            _cfg_logger.warning(
                f"[{self.name}] AgentConfig: interrupt lists are set but "
                f"user_callback=None — all gates will be transparent (fail-open). "
                f"Pass user_callback=async_fn to activate HITL."
            )
        return self
