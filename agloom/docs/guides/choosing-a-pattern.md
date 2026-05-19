# Choosing an execution pattern

You rarely pick a pattern manually — agloom’s **classifier** does. This page helps you **predict** what will run and **steer** behavior when the default routing is not ideal.

## Start here

Read **[Execution patterns](../concepts/patterns.md)** for the nine patterns, diagrams, and when each is selected.

## Decision guide

| Your query looks like… | Likely pattern | How to steer |
| ---------------------- | -------------- | ------------ |
| Short fact or greeting | **DIRECT** | Omit tools; keep query simple |
| Needs calculator, search, APIs | **REACT** | Register tools; clear tool descriptions |
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

## Live bias (CLI / web / custom AGP client)

Send **`command.config.set`** with **`pattern`** when your client supports runtime config updates — useful for demos or power-user overrides without redeploying Python.

## When routing surprises you

1. Enable **`debug=True`** or check **`result.pattern_used`**.
2. Review **`result.steps`** for the classify step metadata.
3. If you use LangSmith, open the trace for the classifier span.
4. Avoid registering tools you do not want the model to use — tools strongly bias toward **REACT**.

## See also

- [Patterns](../concepts/patterns.md)
- [Orchestration](../features/orchestration.md)
- [LCEL as tools](lcel-as-tools.md)
- [AGP protocol](../protocol/agp.md)
