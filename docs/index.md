<div align="center" markdown>

![agloom](https://raw.githubusercontent.com/HELLOMEDHIRA/medhira/main/assets/medhira-logo.png){ width="120" }

# agloom

### The intelligent fabric for AI agents.

Nine execution patterns. Auto-classified. Self-learning. One API.<br>
Drop-in replacement for LangChain's `create_agent` — with superpowers.

[![PyPI](https://img.shields.io/pypi/v/agloom)](https://pypi.org/project/agloom/)
[![Python](https://img.shields.io/pypi/pyversions/agloom)](https://pypi.org/project/agloom/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/HELLOMEDHIRA/agloom/blob/main/LICENSE)
[![Docs](https://readthedocs.org/projects/agloom/badge/?version=latest)](https://agloom.readthedocs.io)

</div>

---

## You write a short async flow. agloom does the rest.

```python
from agloom import create_agent

async def main():
    agent = await create_agent(model=llm, tools=[search, calculate], name="analyst")
    result = await agent.ainvoke("Analyze Q3 sales across 3 regions and recommend strategy")
```

**What happened behind those calls:**

1. Query classified → SUPERVISOR pattern (multi-faceted, parallelizable)
2. Decomposed into 3 regional subtasks
3. 3 workers executed in parallel
4. Results synthesized into a unified recommendation
5. Pattern saved as a reusable skill
6. Quality auto-evaluated and trend-tracked

No routing logic. No worker management. No feedback pipeline. **Just your query and your tools.**

---

## The Problem Every Agent Builder Faces

You want to build an AI agent. LangChain gives you the building blocks — but the assembly is on you:

- **"Which pattern should I use?"** — REACT? Multi-agent? Reflection? You decide per query. At design time.
- **"My agent doesn't learn"** — brilliant response today, starts from zero tomorrow
- **"How do I know if it's working well?"** — no auto-scoring, no trend detection, flying blind
- **"Memory is a nightmare"** — session + long-term + passive injection = weeks of wiring
- **"Users see a loading spinner"** — no streaming, no "thinking" steps, no progress
- **"Production? Good luck."** — timeouts, retries, circuit breakers, rate limiting — DIY everything

**agloom solves all six.** In one function call.

[Read the full story →](_packages/agloom/getting-started/why-agloom.md){ .md-button }

---

## Get Started in 60 Seconds

```python
import asyncio
from langchain_groq import ChatGroq
from agloom import create_agent

async def main():
    llm = ChatGroq(model="meta-llama/llama-4-scout-17b-16e-instruct")
    agent = await create_agent(model=llm, name="my-first-agent")

    result = await agent.ainvoke("What causes auroras?")
    print(result.output)
    print(f"Pattern: {result.pattern_used.value}")  # → DIRECT
    print(f"Steps: {len(result.steps)}")             # → 2

asyncio.run(main())
```

7 lines. Production-grade agent. Auto-classification. Step tracing. Token tracking.

[Install & Quick Start →](_packages/agloom/getting-started/installation.md){ .md-button .md-button--primary }
[CLI Shell →](_packages/agloom_cli/index.md){ .md-button }
[See All 9 Patterns →](_packages/agloom/concepts/patterns.md){ .md-button }

---

## What You Get

| Capability | What it means for you |
|:-----------|:---------------------|
| **9 Execution Patterns** | DIRECT → HYBRID_DAG, auto-selected per query |
| **Skill Learning** | Agents remember what worked and reuse it |
| **Auto-Evaluation** | Every response scored. Trends detected. Skills adjusted |
| **Memory** | Session (always on) + long-term + passive injection. Pass `thread_id` for sessions |
| **Streaming** | Real-time tokens + structured events in one stream. Build ChatGPT-style UIs |
| **Human-in-the-Loop** | 4 interrupt levels: pattern, tool, worker, signal |
| **Production Guards** | Circuit breaker, rate limiter, timeouts, retries |
| **LangSmith** | Auto-detected. Zero code changes |
| **Task Delegation** | 4 patterns: `as_tool()`, hand-off, hierarchical, background. Agents delegate to agents |
| **Frozen Agents** | Classify once, batch thousands |
| **Harness** | `harness=True` + `store=`: task artifact, bootstrap, git helpers. **CLI:** on by default (`graph_store.sqlite`) — [Harness](_packages/agloom/features/harness.md) |

---

## Who Is This For?

- **Developers** — stop writing routing logic and retry plumbing
- **Tech Leads** — standardize your team's agent architecture
- **Product Managers** — ship agent features in days, not weeks
- **AI Engineers** — focus on prompts and tools, not orchestration

---

<div align="center" markdown>

Built with care by **[MEDHIRA](https://github.com/HELLOMEDHIRA)**

[hello.medhira@gmail.com](mailto:hello.medhira@gmail.com)

</div>
