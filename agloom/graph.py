"""
LangGraph StateGraph: START → classify → conditional edge → pattern node → END.

run_fresh() short-circuits DIRECT before invoking the graph (latency), but a
direct node remains so the graph stays testable in isolation and HITL resume
covers every pattern. Each registered handler gets a node so routing never
dead-ends.

Do not pass interrupt_before/after to compile(): run_fresh() handles interrupts
via user_callback. Native compile() interrupts would conflict and block the
pattern node from running.
"""

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from .classifier import analyze_query
from .logging_utils import get_logger
from .models import ExecutionResult, PatternType, QueryAnalysis

logger = get_logger(__name__)


class AgentGraphState(TypedDict):
    """Typed state flowing through every node of the compiled graph."""

    query: str
    analysis: QueryAnalysis | None
    result: ExecutionResult | None


def _get_handlers() -> dict[PatternType, object]:
    """Single source of truth: import handler registry from unified_agent (lazy to avoid circular import)."""
    from .unified_agent import _HANDLERS

    return dict(_HANDLERS)


def _make_classify_node(agent: dict):
    """
    If analysis is already in state (e.g. pre-classified path), skip the LLM;
    otherwise run analyze_query and write the result to state.
    """

    async def classify_node(
        state: AgentGraphState,
        config: RunnableConfig,
    ) -> dict:
        if state.get("analysis") is not None:
            logger.debug(
                f"[Graph:classify] {agent.get('name')} → NO-OP (pre-classified: {state['analysis'].pattern.value})"
            )
            return {}

        analysis = await analyze_query(
            agent["llm"],
            state["query"],
            agent.get("tools", []),
        )
        logger.event(
            f"[Graph:classify] {agent.get('name')} → "
            f"pattern={analysis.pattern.value} | "
            f"complexity={analysis.complexity}/10"
        )
        return {"analysis": analysis}

    classify_node.__name__ = "classify_node"
    return classify_node


def _make_pattern_node(agent: dict, pattern: PatternType, handlers: dict):
    """Dispatch to the handler registered for ``pattern``."""
    handler = handlers[pattern]

    async def pattern_node(
        state: AgentGraphState,
        config: RunnableConfig,
    ) -> dict:
        result = await handler(  # type: ignore[call-arg]
            agent=agent,
            query=state["query"],
            analysis=state["analysis"],
            config=config,
        )
        return {"result": result}

    pattern_node.__name__ = f"{pattern.value.lower()}_node"
    return pattern_node


def _router(state: AgentGraphState) -> str:
    """Route to the pattern node name (``pattern.value.lower()``)."""
    analysis = state.get("analysis")
    if analysis is None:
        logger.error("[Graph:router] analysis is None — routing to __end__")
        return "__end__"
    return analysis.pattern.value.lower()


def build_agent_graph(agent: dict):
    """
    Build and compile the StateGraph for ``agent``. Idempotent: returns an
    existing ``agent["compiled_graph"]`` when set.

    One classify node plus one node per entry in the handler registry.
    """
    # create_agent() sets compiled_graph key to None until first compile
    if agent.get("compiled_graph") is not None:
        return agent["compiled_graph"]

    handlers = _get_handlers()

    builder = StateGraph(AgentGraphState)  # type: ignore[arg-type]

    builder.add_node("classify", _make_classify_node(agent))

    pattern_node_names: list[str] = []
    for pattern in handlers.keys():
        node_name = pattern.value.lower()
        builder.add_node(node_name, _make_pattern_node(agent, pattern, handlers))
        pattern_node_names.append(node_name)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges("classify", _router)
    for node_name in pattern_node_names:
        builder.add_edge(node_name, END)

    compiled = builder.compile(
        checkpointer=agent.get("checkpointer") or None,
        debug=bool(agent.get("debug", False)),
        name=agent.get("name", "UnifiedAgent"),
    )

    agent["compiled_graph"] = compiled

    logger.event(
        f"[Graph] ✅ '{agent.get('name')}' compiled — "
        f"{1 + len(pattern_node_names)} nodes "
        f"(classify + {len(pattern_node_names)} patterns) | "
        f"checkpointer={'yes' if agent.get('checkpointer') else 'no'}"
    )
    return compiled
