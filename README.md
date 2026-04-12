<div align="center">

<img src="https://raw.githubusercontent.com/HELLOMEDHIRA/agloom/main/assets/medhira-logo.svg" width="140" alt="MEDHIRA">

<br>

# agloom

### The intelligent fabric for AI agents.

Nine execution patterns. Auto-classified. Self-learning. One API.<br>
Drop-in replacement for LangChain's `create_agent` — with superpowers.

<br>

[![PyPI version](https://img.shields.io/pypi/v/agloom)](https://pypi.org/project/agloom/)
[![Python 3.11+](https://img.shields.io/pypi/pyversions/agloom)](https://pypi.org/project/agloom/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Docs](https://readthedocs.org/projects/agloom/badge/?version=latest)](https://agloom.readthedocs.io)

[Documentation](https://agloom.readthedocs.io) · [PyPI](https://pypi.org/project/agloom/) · [Examples](https://github.com/HELLOMEDHIRA/agloom/tree/main/examples) · [Issues](https://github.com/HELLOMEDHIRA/agloom/issues)

</div>

<br>

## You write this:

```python
agent = create_agent(model=llm, tools=[search, calculate], name="analyst")
result = await agent.ainvoke("Analyze Q3 sales across 3 regions and recommend strategy")
```

## agloom does this:

```
1. Classifies query         → SUPERVISOR (multi-faceted, parallelizable)
2. Decomposes into 3 tasks  → [Region A, Region B, Region C]
3. Spawns parallel workers   → 3 LLM calls running concurrently
4. Synthesizes results       → Unified strategy recommendation
5. Learns the pattern        → Saved as reusable skill for next time
6. Auto-evaluates quality    → Scored, tracked, trend-detected
```

**Total code you wrote: 2 lines.** Everything else — classification, routing, parallelism, synthesis, learning, evaluation — is handled automatically.

<br>

---

<br>

## Why Teams Choose agloom

<table>
<tr>
<td width="50%">

### Without agloom

```python
# Decide pattern manually per query type
# Build custom routing logic
# Wire up memory yourself
# Implement retry/timeout logic
# Build feedback pipeline
# Add streaming support
# Handle concurrent workers
# Track token costs
# Set up circuit breakers
# ...weeks of infrastructure work
```

</td>
<td width="50%">

### With agloom

```python
from agloom import create_agent

agent = create_agent(
    model=llm,
    tools=[search, calculate],
    name="analyst",
)

result = await agent.ainvoke("Your query here")
# That's it. Everything else is automatic.
```

</td>
</tr>
</table>

<br>

## The Real Cost of Multi-Agent Systems

Building a single agent is manageable. Building a **multi-agent system** — where agents coordinate, delegate, run in parallel, share state, handle failures independently, and synthesize results — is where projects stall for weeks.

Here's what a production multi-agent pipeline actually requires:

```python
# ❌ What you'd build yourself for a multi-agent research pipeline

# 1. Define a supervisor agent that decomposes queries
supervisor_prompt = """You are a research supervisor. Break the query
into subtasks and assign each to a specialist worker..."""
supervisor_chain = prompt | llm | JsonOutputParser()

# 2. Define individual worker agents (each with their own tools, prompts, memory)
researcher = create_react_agent(llm, [search_tool], researcher_prompt)
analyst = create_react_agent(llm, [calc_tool], analyst_prompt)
writer = create_react_agent(llm, [format_tool], writer_prompt)

# 3. Build a state graph for orchestration
class SupervisorState(TypedDict):
    messages: list
    subtasks: list
    worker_results: dict
    final_output: str

graph = StateGraph(SupervisorState)
graph.add_node("supervisor", supervisor_node)
graph.add_node("researcher", researcher_node)
graph.add_node("analyst", analyst_node)
graph.add_node("writer", writer_node)
graph.add_node("synthesizer", synthesizer_node)

# 4. Define routing logic
graph.add_conditional_edges("supervisor", route_to_workers)
graph.add_edge("researcher", "synthesizer")
graph.add_edge("analyst", "synthesizer")
graph.add_edge("writer", "synthesizer")

# 5. Handle parallel execution
async def run_workers(state):
    tasks = [run_worker(w, state) for w in state["subtasks"]]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # Handle partial failures...
    # Retry failed workers...
    # Respect rate limits...
    # Track token usage per worker...

# 6. Add error handling, timeouts, retries per worker
# 7. Wire up memory sharing between workers
# 8. Add streaming from each worker
# 9. Build synthesis logic to merge parallel results
# 10. Track which pattern works best for which query type
# ...easily 300+ lines before it's production-ready
```

Now here's the same thing with agloom:

```python
# ✅ With agloom — same result, zero orchestration code

agent = create_agent(
    model=llm,
    tools=[search_tool, calc_tool, format_tool],
    name="research-team",
)

result = await agent.ainvoke("Research renewable energy trends, analyze the economics, and write a summary")
# agloom auto-selects SUPERVISOR, spawns parallel workers,
# synthesizes results, tracks tokens, and learns the pattern.
```

**300+ lines of orchestration code → 3 lines.** The supervisor logic, worker management, parallel execution, failure handling, result synthesis, and pattern learning are all handled internally. You focus on what your agent should *do*. agloom figures out *how*.

<br>

## What You Get Out of the Box

| Capability | What it means for you |
|:-----------|:---------------------|
| **9 Execution Patterns** | DIRECT, REACT, SUPERVISOR, PIPELINE, PLANNER_EXECUTOR, REFLECTION, SWARM, BLACKBOARD, HYBRID_DAG — auto-selected per query |
| **Zero-Config Classification** | Your agent picks the right strategy for every query. No if-else routing. No manual pattern selection |
| **Skill Learning** | Agents remember what worked. Next time a similar query arrives, they already know the approach |
| **Auto-Evaluation** | Every response is scored. Quality degrades? agloom detects the trend and adjusts |
| **Memory** | Session memory + long-term memory + passive injection. Two parameters: `memory=`, `store=` |
| **Streaming** | Token streaming for responsive UIs. Event streaming for ChatGPT-style "thinking" visibility |
| **Step Tracing** | Full audit trail: classify → tool call → worker → synthesis. Every step timed and logged |
| **Token Tracking** | Know exactly how many tokens each query costs. Across all LLM calls, aggregated |
| **Human-in-the-Loop** | 4 levels of control: pause before patterns, tools, workers, or send runtime signals |
| **Frozen Agents** | Batch mode: classify once, execute thousands. Save ~300ms per call |
| **Production Guards** | Circuit breaker, rate limiter, configurable timeouts, retries, concurrency limits — built in |
| **LangSmith** | Auto-detected. Set the env var, see every trace. No code changes |
| **MCP Support** | Connect to Model Context Protocol servers for external tool discovery |

<br>

## Get Started in 60 Seconds

### Install

```bash
pip install agloom          # or: uv add agloom
pip install agloom[groq]    # with Groq provider
pip install agloom[all]     # all providers
```

### Run

```python
import asyncio
from langchain_groq import ChatGroq
from agloom import create_agent

async def main():
    llm = ChatGroq(model="meta-llama/llama-4-scout-17b-16e-instruct")
    agent = create_agent(model=llm, name="my-first-agent")

    result = await agent.ainvoke("What causes auroras?")
    print(result.output)
    print(f"Pattern: {result.pattern_used.value}")   # → DIRECT
    print(f"Steps:   {len(result.steps)}")            # → 2
    print(f"Tokens:  {result.token_usage}")           # → {input: 48, output: 256}

asyncio.run(main())
```

**That's 7 lines to a production-grade agent with auto-classification, step tracing, and token tracking.**

<br>

## Streaming — Because No One Likes Loading Spinners

```python
# Token streaming — users see the response being typed
async for token in agent.astream("Explain quantum computing"):
    print(token, end="", flush=True)
```

```python
# Event streaming — build ChatGPT-style "thinking" UIs
async for event in agent.astream_events("Research renewable energy"):
    if event.type == "thinking":
        show_spinner(f"Analyzing query...")
    elif event.type == "tool_call":
        show_step(f"Calling {event.data['name']}...")
    elif event.type == "worker_end":
        show_step(f"Worker finished: {event.data['name']}")
    elif event.type == "done":
        show_result(event.data["result"]["output"])
```

<br>

## Battle-Tested Reliability

```python
agent = create_agent(
    model=llm,
    tools=[...],
    name="production-agent",

    # Concurrency
    max_concurrent=8,           # 8 parallel workers
    rate_limit=10.0,            # max 10 LLM calls/sec

    # Resilience
    max_retries=3,              # retry failed workers
    llm_timeout=60.0,           # 60s timeout per LLM call
    # + built-in circuit breaker (automatic)

    # Memory
    store=InMemoryStore(),      # long-term memory + skills + feedback
    memory=SessionMemory(),     # conversation history

    # Quality
    feedback_handler=LTSFeedbackHandler(),  # auto-eval + user feedback
)
```

Every parameter has a sensible default. Start with `create_agent(model=llm)` and add what you need.

<br>

## Who Is This For?

| Role | Why you'll care |
|:-----|:---------------|
| **Developers** | Stop writing agent infrastructure. `create_agent` gives you 9 patterns, memory, streaming, and production guards in one function call |
| **Tech Leads** | Standardize your team's agent architecture. One API, consistent behavior, built-in observability |
| **Product Managers** | Ship agent features faster. What took weeks of custom plumbing now takes one parameter |
| **AI Engineers** | Focus on prompts and tools, not routing logic. agloom handles the orchestration |

<br>

## Documentation

Everything you need at **[agloom.readthedocs.io](https://agloom.readthedocs.io)**:

| Guide | What you'll learn |
|:------|:-----------------|
| [Why agloom?](https://agloom.readthedocs.io/getting-started/why-agloom/) | The 6 problems every agent builder faces and how we solve them |
| [Quick Start](https://agloom.readthedocs.io/getting-started/quickstart/) | First agent in 5 lines of code |
| [Execution Patterns](https://agloom.readthedocs.io/concepts/patterns/) | All 9 patterns with diagrams and examples |
| [All Parameters](https://agloom.readthedocs.io/configuration/parameters/) | Every `create_agent` parameter explained |
| [Streaming & Events](https://agloom.readthedocs.io/features/streaming/) | Build responsive UIs with streaming APIs |
| [Errors & Warnings](https://agloom.readthedocs.io/configuration/errors/) | Every error message, what causes it, how to fix it |
| [LangSmith Integration](https://agloom.readthedocs.io/features/observability/) | Zero-config tracing and observability |

<br>

## Requirements

- **Python** 3.11+
- **LLM API key** — Groq, OpenAI, NVIDIA, HuggingFace, or any LangChain-compatible provider

<br>

## Contributing

We welcome contributions. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and guidelines.

<br>

## License

[Apache 2.0](LICENSE) — use it freely in personal and commercial projects.

<br>

<div align="center">

<img src="https://raw.githubusercontent.com/HELLOMEDHIRA/agloom/main/assets/medhira-logo.svg" width="80" alt="MEDHIRA">

Built with care by **[MEDHIRA](https://github.com/HELLOMEDHIRA)**

[hello.medhira@gmail.com](mailto:hello.medhira@gmail.com) · [GitHub](https://github.com/HELLOMEDHIRA) · [PyPI](https://pypi.org/user/HELLOMEDHIRA/)

<sub>Founded by [S Muni Harish](mailto:samamuniharish@gmail.com)</sub>

</div>
