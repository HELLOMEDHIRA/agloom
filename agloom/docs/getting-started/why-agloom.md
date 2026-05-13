# Why agloom?

## The Pain of Building Agents Today

If you've built agents with LangChain, LangGraph, or any other framework, you've hit these walls:

### 1. "Which execution pattern should I use?"

Every query is different. A simple "Hello" doesn't need a REACT loop. A complex "Analyze sales data across 3 regions" doesn't belong in a single LLM call. But LangChain makes **you** decide the pattern per query at design time.

**agloom fix:** An LLM-powered classifier analyzes every query in real time and routes it to the optimal pattern automatically. Zero configuration.

### 2. "My agent doesn't learn anything"

You build a great agent. It handles a complex query brilliantly. Next time the same type of query comes in — it starts from scratch. No reuse, no improvement.

**agloom fix:** The skill system automatically extracts successful execution patterns into reusable skills. Next time a similar query arrives, the skill is injected into the system prompt.

### 3. "How do I know if my agent is doing well?"

There's no built-in way to score agent outputs, detect quality degradation, or improve over time. You're flying blind.

**agloom fix:** Auto-evaluation scores every run. User feedback is captured. Trend detection spots regressions early. Low-performing skills are decayed and pruned.

### 4. "Memory is a nightmare to wire up"

Session memory, long-term memory, user-scoped memory, passive injection — each requires separate integration, and they don't talk to each other.

**agloom fix:** Session memory is always on — just pass `thread_id` at call time. Add `store=` for long-term memory. Passive injection happens automatically. Memory tools are exposed to the agent by default.

### 5. "I can't show the user what the agent is thinking"

Users see a loading spinner for 10 seconds, then a wall of text. There's no way to stream "thinking" steps, show tool calls, or provide progress.

**agloom fix:** `astream()` for token streaming. `astream_events()` for a live feed of classify → tool call → worker → done events. Build ChatGPT-style UIs with 5 lines of code.

### 6. "Production concerns are all on me"

Timeouts, retries, rate limiting, circuit breakers, concurrent worker limits, structured logging — you build every one from scratch.

**agloom fix:** All of these are built in and configurable via `create_agent` parameters. Set `llm_timeout=60`, `max_retries=3`, `rate_limit=10` and move on.

---

## How agloom Compares

| Capability         | LangChain `create_react_agent` | agloom `create_agent`                                              |
| ------------------ | ------------------------------ | ------------------------------------------------------------------ |
| Patterns           | 1 (REACT only)                 | 9 (auto-selected)                                                  |
| Classification     | Manual                         | Automatic                                                          |
| Skill learning     | No                             | Built-in                                                           |
| Feedback           | No                             | Auto-eval + user + trends                                          |
| Memory             | DIY wiring                     | Always on + `thread_id` + `store=`                                 |
| Streaming          | Basic                          | Combined tokens + events in one stream, real-time for all patterns |
| Token tracking     | No                             | Built-in                                                           |
| HITL               | Basic                          | 4 levels (pattern/tool/worker/signal)                              |
| Timeouts/retries   | DIY                            | Configurable parameters                                            |
| Circuit breaker    | No                             | Built-in                                                           |
| Rate limiting      | No                             | Built-in                                                           |
| Frozen/batch       | No                             | `frozen=True`                                                      |
| LangSmith          | Manual setup                   | Auto-detected                                                      |
| Structured logging | No                             | JSON/text, debug toggle                                            |

## Built on LangChain, Not Against It

agloom is **not** a competing framework. It's built directly on top of LangChain and LangGraph:

- Uses `BaseChatModel` — works with any LangChain-compatible LLM
- Uses `BaseTool` — your existing LangChain tools work unchanged
- Uses `BaseStore` — LangGraph stores for persistence
- Uses `Checkpointer` — LangGraph checkpointing for state recovery
- Auto-detected by **LangSmith** — all traces show up automatically

You keep your existing LangChain ecosystem. agloom just makes it smarter.
