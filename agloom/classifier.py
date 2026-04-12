"""
Query routing (`analyze_query`).

Works with any LangChain-compatible chat model (`BaseChatModel`). The classifier
uses structured output / tool-calling, which is validated against a JSON Schema
at the provider boundary *before* Python sees the payload. Many models return
booleans and integers as strings in that layer; we accept a permissive wire
model (`QueryAnalysisToolPayload`) and map it to the canonical `QueryAnalysis`
used everywhere else in the package.
"""

import asyncio

from langchain_core.messages import HumanMessage, SystemMessage

from .logging_utils import get_logger
from .models import (
    PatternType,
    QueryAnalysis,
    QueryAnalysisToolPayload,
    query_analysis_from_tool_payload,
)

logger = get_logger(__name__)

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


async def analyze_query(
    llm,
    query: str,
    tools: list,
    skill_context: str = "",
    *,
    classifier_timeout: float = 30.0,
    structured_max_retries: int = 2,
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

    prompt = CLASSIFIER_PROMPT.format(
        query=query,
        tools=tools_desc,
    )

    if skill_context:
        prompt = prompt.replace(
            "QUERY TO ANALYZE",
            f"AVAILABLE SKILLS\n{'=' * 55}\n\n{skill_context}\n\n\n{'=' * 55}\nQUERY TO ANALYZE",
            1,
        )

    has_tools = bool(tools)

    from .llm_utils import robust_structured_call

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

        logger.event(
            f"[Classifier] ✅ Pattern={analysis.pattern.value:<20} "
            f"| Complexity={analysis.complexity}/10 "
            f"| {analysis.reasoning}"
        )
        return analysis

    except Exception as e:
        logger.warning(
            f"[Classifier] ⚠ Structured output failed ({e}) — falling back to {'REACT' if has_tools else 'DIRECT'}."
        )

        if has_tools:
            return QueryAnalysis(
                pattern=PatternType.REACT,
                complexity=5,
                reasoning=("Structured output failed — defaulting to REACT so available tools remain accessible."),
                direct_response=None,
                subtasks=[],
                estimated_steps=3,
            )

        try:
            raw_resp = await asyncio.wait_for(
                llm.ainvoke([HumanMessage(content=query)]),
                timeout=classifier_timeout,
            )
            fallback_answer = raw_resp.content
        except Exception:
            fallback_answer = "Unable to process query."

        return QueryAnalysis(
            pattern=PatternType.DIRECT,
            complexity=1,
            reasoning="Structured output failed, no tools available — treated as DIRECT.",
            direct_response=fallback_answer,
            estimated_steps=1,
        )
