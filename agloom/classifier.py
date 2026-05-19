"""Query classification: ``analyze_query`` maps user text to ``QueryAnalysis`` (pattern, subtasks, DIRECT answer).

Uses structured output / tool-calling on ``BaseChatModel``. Provider payloads are normalized through
``QueryAnalysisToolPayload`` before building canonical ``QueryAnalysis``.
"""

import asyncio

from langchain_core.messages import HumanMessage, SystemMessage

from .logging_utils import get_logger
from .llm_utils import robust_structured_call
from .models import (
    PatternType,
    QueryAnalysis,
    QueryAnalysisToolPayload,
    query_analysis_from_tool_payload,
)

logger = get_logger(__name__)

_CLASSIFIER_FALLBACK_SYSTEM = """\
You are a helpful assistant. A structured classifier step failed upstream.
Reply with a concise, direct answer to the user only—plain text, no JSON wrapper, \
no mention of classifiers or errors unless the user asked about them.\
"""

CLASSIFIER_PROMPT = """\
You are a Query Analyzer AND Responder for an adaptive AI agent system.

Your job:
  1. Classify the query complexity.
  2. Select the right execution pattern.
  3. For DIRECT queries — answer them yourself inline (direct_response field).
  4. For all other patterns — plan the subtasks for specialist agents.

═══════════════════════════════════════════════════════════
PATTERNS
═══════════════════════════════════════════════════════════

DIRECT  (complexity 0–2)
  ├─ No tools. No agents. YOU answer it right now.
  ├─ direct_response = your full answer
  └─ Examples: "Hi", "What is 2+2?", "What is Python?",
               "Tell me a joke", "What's your name?"


REACT  (complexity 3–4)
  ├─ Single agent + tool loop. 1–3 tool calls needed.
  ├─ direct_response = null
  └─ Examples: "Search arXiv for attention papers",
               "Calculate compound interest for 5 years",
               "Extract keywords from this text"


SUPERVISOR  (complexity 5–6)
  ├─ Multiple PARALLEL independent workers, central manager aggregates.
  ├─ ALL depends_on = [] for every worker — they ALL run simultaneously.
  ├─ direct_response = null
  └─ Examples: "Research LLMs, RAG, and Agents separately",
               "Compare Python vs Go vs Rust performance"


PIPELINE  (complexity 5–6)
  ├─ Fixed linear transformation chain — each step transforms the previous output.
  ├─ Pure A→B→C→D, no branching, no parallel steps.
  ├─ depends_on chains strictly: worker_2→[worker_1], worker_3→[worker_2], etc.
  ├─ direct_response = null
  └─ Examples: "Translate → summarize → extract keywords → format as JSON"


PLANNER_EXECUTOR  (complexity 6–7)
  ├─ Sequential — each step DEPENDS on and REASONS from the previous step's output.
  ├─ depends_on chains in strict order.
  ├─ direct_response = null
  └─ Examples: "Find the top paper → extract its keywords → search related papers"


REFLECTION  (complexity 7–8)
  ├─ Single goal: generate → critique → refine loop until quality threshold met.
  ├─ needs_reflection = true, exactly 1 subtask describing the overall goal.
  ├─ direct_response = null
  └─ Examples: "Write a rigorous literature review on transformers"


SWARM  (complexity 7–9)
  ├─ Multiple INDEPENDENT agents, NO central manager — agents self-coordinate.
  ├─ Each worker has a distinct role/perspective. ALL depends_on = [].
  ├─ direct_response = null
  └─ Examples: "Debate pros and cons of microservices vs monolith"


BLACKBOARD  (complexity 8–10)
  ├─ Shared evolving state — agents read AND write to a common blackboard.
  ├─ Each agent sees ALL prior agents' outputs before running.
  ├─ Sequential contribution order driven by trigger conditions (not fixed DAG).
  ├─ direct_response = null
  ├─ Signals: "iteratively refine", "critique then improve", "build on each other's work"
  └─ Examples:
       "Research X, then critique the research, then refine based on the critique"
       "Multiple agents collaboratively build a system design document"
       "Agent A produces draft → Agent B critiques → Agent C refines the draft"

  BLACKBOARD vs HYBRID_DAG:
    HYBRID_DAG  → each worker sees ONLY its direct deps (selective context)
    BLACKBOARD  → every worker sees the ENTIRE board (full shared context)


HYBRID_DAG  (complexity 8–10)
  ├─ Mixed dependency graph — some parallel, some sequential.
  ├─ Workers see ONLY their direct dependency outputs (not global state).
  ├─ direct_response = null
  └─ Examples: "Research 3 topics in parallel, analyze each after research
                completes, then synthesize into a final report"


═══════════════════════════════════════════════════════════
PATTERN DECISION FLOWCHART
═══════════════════════════════════════════════════════════

  Can YOU answer right now — no tools needed?               → DIRECT
  Needs 1–3 tool calls, single agent sufficient?            → REACT
  Multiple subtasks, ALL fully independent + manager?       → SUPERVISOR
  Pure fixed transformation chain (A→B→C→D)?                → PIPELINE
  All steps sequential, each REASONS from prior output?     → PLANNER_EXECUTOR
  Single goal, critique + refine loop needed?               → REFLECTION
  Multiple agents, NO manager, adversarial/debate?          → SWARM
  BOTH parallel AND sequential workers in same task?        → HYBRID_DAG
  Long-running, agents need shared evolving state?          → BLACKBOARD


═══════════════════════════════════════════════════════════
MEMORY TOOL RULE  ⚠ HIGHEST PRIORITY — READ FIRST
═══════════════════════════════════════════════════════════

If the available tools include `save_memory` or `recall_memory`:

  SAVING facts → ALWAYS REACT. NEVER DIRECT.
    Signals: "remember", "save", "note that", "keep in mind",
             "my name is", "I am a", "I work at", "store this"
    → pattern = REACT, required_tools = ["save_memory"]

  RECALLING facts → ALWAYS REACT. NEVER DIRECT.
    Signals: "what do you know about", "what does X do",
             "who is X", "recall", "do you remember",
             queries about a named person/thing previously mentioned
    → pattern = REACT, required_tools = ["recall_memory"]

  DIRECT means zero tool calls. It cannot save or recall ANYTHING.
  A DIRECT response that says "I've saved your info" is a HALLUCINATION.


═══════════════════════════════════════════════════════════
FILE / WORKSPACE / SHELL RULE  ⚠ HIGHEST PRIORITY (CLI CODING AGENT)
═══════════════════════════════════════════════════════════

When **any** filesystem, shell, or workspace tools are listed below (e.g. read_file,
list_directory, run_shell, grep_files, write_file, …):

  • You do **not** retain project file contents in classifier memory. You cannot truthfully
    paste or summarize files without a tool call in the execution phase.

  • ANY user request to **read**, **show**, **display**, **print**, **retry**, **again**,
    **lines** of a file, **open** a path, **search** the repo, **list** directories, or
    **run** shell commands → **pattern = REACT**, **direct_response = null**.

  • **Never** choose DIRECT with a fake code block, placeholder comment, or text that says
    "content wasn't stored — call read_file" — that is wrong. Route to REACT so the agent
    invokes tools.

  • Pure conceptual questions ("what is a .py file?", "what does read_file do?") with **no**
    request to inspect **this** project may stay DIRECT.

  Signals that almost always require REACT when tools exist:
    file paths, extensions (.py, .toml, .md, …), "pyproject", "lines", "top/last/first N",
    "read the", "show the", "contents", "directory", "folder", "grep", "run cmd", "retry".

  • In ``reasoning``, describe **only the current user message**. Do not continue a prior turn's
    task (e.g. an earlier ``pyproject.toml`` read) unless the user explicitly refers back to it.


═══════════════════════════════════════════════════════════
STRICT FIELD RULES
═══════════════════════════════════════════════════════════

  DIRECT           → direct_response = your answer    | subtasks = []
  REACT            → direct_response = null           | subtasks = []
  SUPERVISOR       → direct_response = null           | ALL depends_on = []
  PIPELINE         → direct_response = null           | strict linear depends_on chain
  PLANNER_EXECUTOR → direct_response = null           | strict sequential depends_on chain
  REFLECTION       → direct_response = null           | exactly 1 subtask | needs_reflection = true
  SWARM            → direct_response = null           | ALL depends_on = []
  BLACKBOARD       → direct_response = null           | subtasks describe roles + shared state keys
  HYBRID_DAG       → direct_response = null           | mix of depends_on=[] and depends_on=[worker_n]

  worker_ids must be unique strings: "worker_1", "worker_2", etc.
  required_tools must ONLY use names from: {tools}
  If no tools needed for a subtask: required_tools = []

  context field MUST be dict[str, str] — flat key/value pairs only.
  NEVER use lists or nested objects in context.
  ✅ CORRECT:   "context": {{"entity": "Priya", "role": "data scientist"}}
  ❌ INCORRECT: "context": {{"facts": ["name": "Priya", "role": "data scientist"]}}

  Tool fields complexity, estimated_steps, can_parallelize, and needs_reflection
  use string values (e.g. "5", "1", "false", "true") so strict tool JSON Schema
  validation succeeds across providers; the runtime maps them to proper types.

═══════════════════════════════════════════════════════════
ORCHESTRATION PLAN (per-turn budgets; omit or "" to use defaults)
═══════════════════════════════════════════════════════════

  When the deployment allows recursive orchestration, also set:

  orchestration_depth (string int, 0–20)
    Suggested max recursive pattern depth for THIS query.
    0 = no sub-pattern recursion (simple / DIRECT-class queries).
    1–2 = light recovery spawns; 3–4 = deep multi-pattern work.
    Must not exceed the agent ceiling configured by the operator.

  orchestration_token_budget (string int)
    Suggested total orchestration token budget for this turn (e.g. "8000", "50000").
    Use "" when unsure.

  orchestration_llm_call_budget (string int)
    Suggested max orchestration LLM calls (classifier + spawns + eval), e.g. "15", "50".

  orchestration_auto_escalation ("true" / "false" / "")
    "true" only for hard queries (complexity ≥ 7) where follow-up patterns may help.
    "" = let runtime derive from complexity.

  Guidelines:
    complexity 0–2  → depth "0", auto_escalation "false"
    complexity 3–4  → depth "1", auto_escalation "false"
    complexity 5–6  → depth "2", auto_escalation "false"
    complexity 7–8  → depth "3", auto_escalation "true"
    complexity 9–10 → depth "4", auto_escalation "true"

  system_instruction MUST be a non-empty string for every subtask.
  It defines the worker's role and persona. Be specific and role-appropriate.
  BAD:  "You are a helpful AI assistant."
  GOOD: "You are a senior data analyst. Extract quantitative insights from the
        provided data and present them as bullet points with supporting numbers.


═══════════════════════════════════════════════════════════
QUERY TO ANALYZE
═══════════════════════════════════════════════════════════

Query: {query}
"""

_QUERY_SLOT_MARKER_PREFIX = "\ufeffAGLOOM_CLASSIFIER_QUERY_"


def build_classifier_user_prompt(*, tools_desc: str, query: str) -> str:
    """Fill :data:`CLASSIFIER_PROMPT` so user *query* and *tools_desc* cannot corrupt each other.

    Uses a per-call random slot marker so a user query cannot collide with the placeholder.
    Only the dedicated ``Query: …`` slot is substituted (``replace(..., 1)``).
    """
    import secrets

    marker = f"{_QUERY_SLOT_MARKER_PREFIX}{secrets.token_hex(8)}\ufeff"
    return (
        CLASSIFIER_PROMPT.replace("{query}", marker, 1)
        .replace("{tools}", tools_desc, 1)
        .replace(marker, query, 1)
    )


async def analyze_query(
    llm,
    query: str,
    tools: list,
    skill_context: str = "",
    *,
    classifier_timeout: float = 60.0,
    structured_max_retries: int = 2,
    fallback_pattern: PatternType | None = None,
) -> QueryAnalysis:
    """
    Single LLM call → QueryAnalysis.

    Parameters
    ----------
    llm            : BaseChatModel-compatible model.
    query          : The user query (may include injected memory context).
    tools          : List of tool objects with ``.name`` / ``.description`` attributes,
                     **or** an empty list when no tools are registered.
    skill_context  : Optional skill manifest lines injected by SkillInjector.
                     When present, added to the prompt before the query section.

    Uses ``QueryAnalysisToolPayload`` as the structured-output / tool-call shape:
    provider-side JSON Schema often requires exact scalar types, while models
    frequently emit strings for numbers and booleans. The wire model accepts
    that; ``query_analysis_from_tool_payload`` yields a strict ``QueryAnalysis``
    for the rest of the stack (graph, patterns, memory).

    Fallback:
      If structured output fails after LLM retries (e.g., model doesn't
      support tool calling, or malformed generation):
        - tools non-empty → REACT  (tools exist to be called)
        - tools empty     → DIRECT (no tools, safe to answer inline)
      NEVER defaults to DIRECT when tools are available — that would
      cause memory saves/recalls to silently hallucinate.
    """
    tools_desc = "\n".join(f"  - {t.name}: {getattr(t, 'description', '')}" for t in tools) or "none"

    prompt = build_classifier_user_prompt(tools_desc=tools_desc, query=query)

    if skill_context:
        prompt = prompt.replace(
            "QUERY TO ANALYZE",
            f"AVAILABLE SKILLS\n{'=' * 55}\n\n{skill_context}\n\n\n{'=' * 55}\nQUERY TO ANALYZE",
            1,
        )

    has_tools = bool(tools)

    try:
        raw = await robust_structured_call(
            llm,
            QueryAnalysisToolPayload,
            [
                SystemMessage(
                    content=(
                        "You are a query classifier for an adaptive AI agent system. "
                        "Analyze the query and return a structured classification."
                    )
                ),
                HumanMessage(content=prompt),
            ],
            max_retries=structured_max_retries,
            timeout=classifier_timeout,
            caller="Classifier",
        )
        if raw is None:
            raise ValueError("All structured output strategies exhausted")
        analysis = query_analysis_from_tool_payload(
            raw,
            tools_available=has_tools,
        )

        reasoning = (analysis.reasoning or "").strip()
        logger.event(
            f"[Classifier] ✅ Pattern={analysis.pattern.value:<20} "
            f"| Complexity={analysis.complexity}/10 "
            f"| {reasoning}"
        )
        return analysis

    except Exception as e:
        default_fb = fallback_pattern or (PatternType.REACT if has_tools else PatternType.DIRECT)
        logger.warning(
            f"[Classifier] ⚠ Structured output failed ({e}) — falling back to {default_fb.value}. "
            "If logs show TimeoutError on json_schema/function_calling, increase "
            "`execution.classifier_timeout` (seconds per attempt; slow models often need 90–120)."
        )

        if default_fb != PatternType.DIRECT:
            return QueryAnalysis(
                pattern=default_fb,
                complexity=5,
                reasoning=(
                    f"Structured output failed — defaulting to {default_fb.value} "
                    f"{'so available tools remain accessible' if has_tools else '(configured fallback)'}."
                ),
                direct_response=None,
                subtasks=[],
                estimated_steps=3,
            )

        try:
            raw_resp = await asyncio.wait_for(
                llm.ainvoke(
                    [
                        SystemMessage(content=_CLASSIFIER_FALLBACK_SYSTEM),
                        HumanMessage(content=query),
                    ]
                ),
                timeout=classifier_timeout,
            )
            from .multimodal import content_blocks_to_text

            fallback_answer = content_blocks_to_text(raw_resp.content)
        except Exception:
            fallback_answer = "Unable to process query."

        return QueryAnalysis(
            pattern=PatternType.DIRECT,
            complexity=1,
            reasoning="Structured output failed, no tools available — treated as DIRECT.",
            direct_response=fallback_answer,
            estimated_steps=1,
        )
