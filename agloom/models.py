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

DEFAULT_SYSTEM_PROMPT = "You are a helpful, precise AI assistant. Think step by step. Be concise and accurate."


class SignalType(str, Enum):
    """
    Level 4 signals emitted into agent["signal_queue"].
    HALT_ALL              → cancel all running worker tasks immediately
    CLARIFICATION_REQUEST → worker needs human input before continuing
    SUCCESS               → worker completed normally
    FAILED                → worker failed after retries
    """

    HALT_ALL = "HALT_ALL"
    CLARIFICATION_REQUEST = "CLARIFICATION_REQUEST"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


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

    @field_validator("complexity", "estimated_steps", mode="before")
    @classmethod
    def _coerce_int_fields(cls, v: Any) -> Any:
        """Structured tool output often sends ints as strings; normalize here."""
        if v is None:
            return v
        if isinstance(v, bool):
            return v
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

    @field_validator("direct_response", mode="before")
    @classmethod
    def _nullish_direct(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str) and v.strip().lower() in ("", "null", "none", "undefined"):
            return None
        return v

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
        if v is None:
            return "false"
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v).strip().lower()


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

    can_parallelize = (
        raw.can_parallelize.lower() == "true" if isinstance(raw.can_parallelize, str) else bool(raw.can_parallelize)
    )

    # REFLECTION pattern without needs_reflection=True silently skips
    # the critique loop in patterns/reflection.py — enforce the invariant.
    _needs_reflection = (
        raw.needs_reflection.lower() == "true" if isinstance(raw.needs_reflection, str) else bool(raw.needs_reflection)
    )
    needs_reflection = True if pattern == PatternType.REFLECTION else _needs_reflection

    reasoning = raw.reasoning or f"Routed to {pattern.value} pattern."

    direct_response = raw.direct_response if pattern == PatternType.DIRECT else None

    subtasks = raw.subtasks if isinstance(raw.subtasks, list) else []

    matched_skill = getattr(raw, "matched_skill", None)
    if matched_skill and isinstance(matched_skill, str):
        matched_skill = matched_skill.strip() or None

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
    TOKEN = "token"  # noqa: S105


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
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    pattern_used: PatternType
    query: str
    output: str
    steps_taken: int = 0
    success: bool = True
    analysis: QueryAnalysis | None = None
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


DEFAULT_STEP_MAX_LENGTH: int = 0


def _trunc(s: str, limit: int = DEFAULT_STEP_MAX_LENGTH) -> str:
    """Truncate string to *limit* chars. 0 or negative → no truncation."""
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


def _extract_token_usage(response: Any) -> dict[str, int]:
    """Extract token usage from a LangChain AIMessage or response dict."""
    usage: dict[str, int] = {}
    messages = None
    if isinstance(response, dict):
        messages = response.get("messages", [])
    elif hasattr(response, "messages"):
        messages = response.messages
    if messages:
        for msg in reversed(messages):
            meta = getattr(msg, "usage_metadata", None)
            if meta:
                if isinstance(meta, dict):
                    usage = {k: v for k, v in meta.items() if isinstance(v, int)}
                else:
                    for field in ("input_tokens", "output_tokens", "total_tokens"):
                        val = getattr(meta, field, None)
                        if val is not None:
                            usage[field] = int(val)
                break
    if not usage and hasattr(response, "usage_metadata") and response.usage_metadata:
        meta = response.usage_metadata
        if isinstance(meta, dict):
            usage = {k: v for k, v in meta.items() if isinstance(v, int)}
        else:
            for field in ("input_tokens", "output_tokens", "total_tokens"):
                val = getattr(meta, field, None)
                if val is not None:
                    usage[field] = int(val)
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
    for example ``delegates``, ``feedback_handler``, ``frozen`` / ``frozen_template``,
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
    user_callback: Any = None  # Callable | None

    debug: bool = False
    max_concurrent: int = Field(default=4, ge=1, le=32)
    max_retries: int = Field(default=2, ge=0, le=10)
    retry_delay: float = Field(default=1.0, ge=0.0)

    llm_timeout: float = Field(
        default=120.0, ge=1.0, description="Default timeout (s) for non-structured LLM ainvoke calls"
    )
    classifier_timeout: float = Field(
        default=30.0, ge=1.0, description="Timeout (s) for the classifier structured call"
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
    session_max_turns: int = Field(default=20, ge=1)
    max_reflection_iterations: int = Field(default=3, ge=1)
    reflection_threshold: int = Field(default=7, ge=0, le=10)

    auto_summarize: bool = Field(default=True, description="Enable auto-summarization of conversation history")
    summarize_threshold: int = Field(
        default=200_000, ge=10_000, description="Token count threshold that triggers auto-summarization"
    )
    summarizer_model: Any = None

    mcp_servers: list[Any] = Field(default_factory=list)

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
