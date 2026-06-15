# Choosing an execution pattern

You rarely pick a pattern manually — agloom’s **classifier** does. This page helps you **predict** what will run and **steer** behavior when the default routing is not ideal.

## Start here

Read **[Execution patterns](../concepts/patterns.md)** for the nine patterns, diagrams, and when each is selected.

## Decision guide

| Your query looks like… | Likely pattern | How to steer |
| ---------------------- | -------------- | ------------ |
| Short fact or greeting | **DIRECT** | Omit tools; keep query simple |
| Needs calculator, search, APIs | **REACT** | Register tools; clear tool descriptions |
| Investigate logs, metrics, traces (MCP) | **REACT** | Configure `mcp_servers`; avoid REFLECTION for raw fetch — see below |
| Several independent research tasks | **SUPERVISOR** | Ask for comparison / parallel facets explicitly |
| Strict step 1 → 2 → 3 | **PIPELINE** | Number steps in the prompt |
| Long plan with revisiting earlier work | **PLANNER** | Ask for plan + execute phases |
| Must be polished (writing, specs) | **REFLECTION** | Raise quality bar in prompt; tune `reflection_threshold` |
| Debate / pros & cons | **SWARM** | Ask for multiple viewpoints |
| Experts building shared notes | **BLACKBOARD** | Complex multi-specialist tasks |
| Mixed parallel then merge | **HYBRID** | Describe dependencies in the query |

## Practical shortcuts

- **Tool-heavy exploration** — register tools; classifier usually picks **REACT**.
- **Known fixed workflow** — describe ordered steps; **PIPELINE** or **PLANNER** often win.
- **LCEL inside one capability** — wrap chains as tools ([LCEL as tools](lcel-as-tools.md)); orchestration stays automatic.

## MCP and observability queries

When **`mcp_servers`** is set (Grafana, Loki, Elasticsearch, custom observability MCP, etc.):

- **Investigation / fetch** prompts (“show errors in the last hour”, “why did latency spike”, “query logs for checkout”) should run as **REACT** with MCP tool calls — not **DIRECT** (hallucinated telemetry) or **REFLECTION** (generate→critique loop without a guaranteed fetch step).
- The classifier prompt encodes this rule; agloom **coerces** mis-routed **DIRECT** or **REFLECTION** classifications to **REACT** when the query matches observability-fetch heuristics.
- Set **`react_force_tool_choice_on_user_turn=True`** (default) so the first model turn after each user message requests a structured tool call — applies to **REACT** and to **workers** inside other patterns when they have tools.

Details: [MCP Server Integration](../features/mcp.md#classifier-routing-with-mcp).

## Live bias (CLI / web / custom AGP client)

Send **`command.config.set`** with **`pattern`** when your client supports runtime config updates — useful for demos or power-user overrides without redeploying Python.

## When routing surprises you

1. Enable **`debug=True`** or check **`result.pattern_used`**.
2. Review **`result.steps`** for the classify step metadata.
3. If you use LangSmith, open the trace for the classifier span.
4. Avoid registering tools you do not want the model to use — tools strongly bias toward **REACT**.

## See also

- [Patterns](../concepts/patterns.md)
- [MCP Server Integration](../features/mcp.md)
- [Orchestration](../features/orchestration.md)
- [LCEL as tools](lcel-as-tools.md)
- [AGP protocol](../protocol/agp.md)
