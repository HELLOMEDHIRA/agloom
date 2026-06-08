# agloom (Python package)

The **`agloom`** PyPI package is a production-minded agent framework on LangChain/LangGraph: nine execution patterns, automatic routing, memory, streaming, skills, and optional harness tooling.

---

## Install

```bash
pip install agloom
# optional: pip install agloom[groq]
```

| Artifact | Role |
| -------- | ---- |
| **`agloom` library** | `create_agent`, tools, memory, patterns |
| **`agloom-runtime`** | AGP bridge for CLI, web, and custom servers |
| **`agloom` console script** | Points to the npm CLI — not the interactive TUI |

**Interactive terminal:** [agloom-cli](https://www.npmjs.com/package/agloom-cli) (repo folder `agloom_cli/`).  
**Browser workspace:** `agloom_web/` in the repo.

---

## Your first agent

```python
import asyncio
from langchain_groq import ChatGroq
from agloom import create_agent

async def main():
    llm = ChatGroq(model="llama-3.3-70b-versatile")
    agent = await create_agent(model=llm, name="demo")
    result = await agent.ainvoke("What causes auroras?")
    print(result.output)
    print(result.pattern_used)

asyncio.run(main())
```

**Documentation:** [agloom.readthedocs.io](https://agloom.readthedocs.io)

---

## What agloom automates

| You write | agloom runs |
| --------- | ----------- |
| Model + tools | Pattern selection per turn |
| `thread_id` | Session memory |
| `store=` | Long-term memory, skills, quality scoring |
| `astream_events()` | Live “thinking”, tools, tokens |
| Production knobs | Timeouts, retries, rate limits, circuit breaker |

---

## Integration paths

1. **Application** — embed `create_agent` in your service ([quick start](https://agloom.readthedocs.io/_packages/agloom/getting-started/quickstart/))
2. **Streaming UI** — `astream_events` or `astream_agp_events` ([streaming guide](https://agloom.readthedocs.io/_packages/agloom/features/streaming/))
3. **AGP clients** — `agloom-runtime serve` + CLI/web ([integration overview](https://agloom.readthedocs.io/_packages/agloom/guides/developer-overview/))

Examples: `agloom/examples/` on GitHub.
