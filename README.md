<div align="center">

<img src="https://raw.githubusercontent.com/HELLOMEDHIRA/medhira/main/assets/medhira-logo.png" width="140" alt="agloom">

<br>

# agloom

**Build agents that route themselves.**  
One familiar API — classification, memory, streaming, guardrails, and learning included.

Nine execution patterns. Auto-selected per task. Skills improve over time.

<br>

[![PyPI version](https://img.shields.io/pypi/v/agloom)](https://pypi.org/project/agloom/)
[![Python 3.12](https://img.shields.io/pypi/pyversions/agloom)](https://pypi.org/project/agloom/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Docs](https://readthedocs.org/projects/agloom/badge/?version=latest)](https://agloom.readthedocs.io)

**[Documentation](https://agloom.readthedocs.io)** · **[Quick Start](https://agloom.readthedocs.io/_packages/agloom/getting-started/quickstart/)** · [PyPI](https://pypi.org/project/agloom/) · [Examples](https://github.com/HELLOMEDHIRA/agloom/tree/main/agloom/examples) · [Issues](https://github.com/HELLOMEDHIRA/agloom/issues)

</div>

<br>

## Start here

**agloom** is a Python framework for production-minded agents on **LangChain / LangGraph**. You describe the model and tools; agloom picks how to run the task (single-shot, ReAct, supervisor-style delegation, pipelines, and more), tracks steps and tokens, and can learn reusable **skills** from what worked.

If you already use LangChain’s agent APIs, think of **`create_agent`** as your main entrypoint — with orchestration, memory, streaming, and safety knobs in one place.

### Install

```bash
pip install agloom
# optional extras, e.g. Groq:
pip install agloom[groq]
```

### Your first agent

```python
import asyncio
from langchain_groq import ChatGroq
from agloom import create_agent

async def main():
    llm = ChatGroq(model="meta-llama/llama-4-scout-17b-16e-instruct")
    agent = await create_agent(model=llm, name="my-agent")
    result = await agent.ainvoke("What causes auroras?")
    print(result.output)

asyncio.run(main())
```

`create_agent` is **async** (use `await`). From synchronous code, use **`create_agent_sync`**.

**Next steps:** [Why agloom?](https://agloom.readthedocs.io/_packages/agloom/getting-started/why-agloom/) · [Patterns explained](https://agloom.readthedocs.io/_packages/agloom/concepts/patterns/) · [All parameters](https://agloom.readthedocs.io/_packages/agloom/configuration/parameters/)

<br>

## What you get (in plain language)

| You want to…      | agloom helps by…                                                        |
| ----------------- | ----------------------------------------------------------------------- |
| Ship faster       | Picking a strategy per query instead of hand-writing routers and graphs |
| Keep context      | Session memory by default; optional long-term memory and skills         |
| Show progress     | Token streaming plus structured events for “thinking” / tool UIs        |
| Stay safe         | Human-in-the-loop levels, timeouts, retries, rate limits — configurable |
| Improve over time | Skill library and feedback hooks so behavior compounds                  |

For the full feature tour, see **[What you get](https://agloom.readthedocs.io/_packages/agloom/getting-started/why-agloom/)** in the docs — the README stays short on purpose.

<br>

## agloom CLI & web workspace

- **Terminal:** the **agloom CLI** (npm `agloom-cli`, repo **`agloom_cli/`**) is the terminal client — UI built with **Ink** and **React**. From that folder: `npm install` → `npm run build` → `npm start`. It talks to **`agloom-runtime`** over AGP (stdio by default). [CLI quick start](agloom_cli/docs/index.md)
- **Browser:** **`agloom_web/`** is the Vite workspace for sessions and observability — same idea, run commands inside that folder.

PyPI’s **`agloom`** package includes the library and **`agloom-runtime`**. The **`agloom`** command prints a short pointer to the **agloom CLI** (repo folder `agloom_cli/`) for backwards compatibility.

<br>

## Learn more (documentation hub)

| Guide                                                                                     | What it’s for                             |
| ----------------------------------------------------------------------------------------- | ----------------------------------------- |
| [Quick Start](https://agloom.readthedocs.io/_packages/agloom/getting-started/quickstart/) | Smallest path to a running agent          |
| [Execution patterns](https://agloom.readthedocs.io/_packages/agloom/concepts/patterns/)   | How routing works (conceptual + diagrams) |
| [Streaming & events](https://agloom.readthedocs.io/_packages/agloom/features/streaming/)  | Responsive UI patterns                    |
| [Production](https://agloom.readthedocs.io/_packages/agloom/guides/production/)           | Deploying, testing, operating             |
| [Errors & fixes](https://agloom.readthedocs.io/_packages/agloom/configuration/errors/)    | When something goes wrong                 |

<br>

## Requirements

- **Python** 3.12.x (see `pyproject.toml` on GitHub for the exact pin)
- **Node.js** ≥ 24.15.0 — only if you hack on **`agloom_cli/`** or **`agloom_web/`**
- An **LLM API key** (Groq, OpenAI, NVIDIA, Hugging Face, or another LangChain-compatible provider)

<br>

## Contributing & license

Contributions welcome — see **[CONTRIBUTING.md](CONTRIBUTING.md)**.

Licensed under **[Apache 2.0](LICENSE)**.

<br>

<div align="center">

<img src="https://raw.githubusercontent.com/HELLOMEDHIRA/medhira/main/assets/medhira-logo.png" width="80" alt="agloom">

**agloom** is built by **[MEDHIRA](https://github.com/HELLOMEDHIRA)**

[hello.medhira@gmail.com](mailto:hello.medhira@gmail.com) · [GitHub](https://github.com/HELLOMEDHIRA) · [PyPI](https://pypi.org/user/HELLOMEDHIRA/)

<sub>Founded by [S Muni Harish](mailto:samamuniharish@gmail.com)</sub>

</div>
