"""
LangGraph StateGraph: START → classify → conditional edge → pattern node → END.

run_fresh() short-circuits DIRECT before invoking the graph (latency), but a
direct node remains so the graph stays testable in isolation. HITL ``resume()``
can preload ``analysis`` into state so classify does not re-run after an interrupt.
Each registered handler gets a node so routing never dead-ends.

Do not pass interrupt_before/after to compile(): run_fresh() handles interrupts
via user_callback. Native compile() interrupts would conflict and block the
pattern node from running.
"""

from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from .logging_utils import get_logger
from .models import ExecutionResult, PatternType, QueryAnalysis

logger = get_logger(__name__)


def _merge_handler_invoke_config(runnable_config: RunnableConfig | dict | None) -> dict:
    """Flatten LangGraph ``RunnableConfig`` into the per-run dict pattern handlers expect."""
    out: dict = {"_steps": []}
    if not runnable_config:
        return out
    try:
        rd = dict(runnable_config)  # RunnableConfig is mapping-like
    except Exception:
        return out
    cfg = rd.get("configurable")
    if isinstance(cfg, dict):
        out.update(cfg)
    return out


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
    """Classify node: skip when ``analysis`` is already in state.

    State may be preloaded before ``resume()`` (checkpoint or in-process cache) so the
    pattern is not re-selected mid-interrupt. Otherwise runs the same classifier path
    as a normal ``ainvoke`` turn.
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

        from .unified_agent import _execute_analyze_query

        skill_ctx = ""
        skill_injector = agent.get("skill_injector")
        if skill_injector is not None:
            try:
                skill_ctx = await skill_injector.get_context(state["query"])
            except Exception as exc:
                logger.warning(
                    f"[Graph:classify] {agent.get('name')} skill_injector failed ({exc!r}) — proceeding without."
                )

        analysis = await _execute_analyze_query(
            agent,
            augmented_query=state["query"],
            skill_context=skill_ctx,
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
        result = await cast(Any, handler)(
            agent=agent,
            query=state["query"],
            analysis=state["analysis"],
            config=_merge_handler_invoke_config(config),
        )
        return {"result": result}

    pattern_node.__name__ = f"{pattern.value.lower()}_node"
    return pattern_node


def _router(state: AgentGraphState) -> str:
    """Route to the pattern node name (``pattern.value.lower()``)."""
    analysis = state.get("analysis")
    if analysis is None:
        logger.error("[Graph:router] analysis is None — routing to END")
        return END
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

    builder = StateGraph(cast(Any, AgentGraphState))

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
