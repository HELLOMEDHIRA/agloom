# Choosing an execution pattern

agloom routes work through **patterns** (ReAct, sequential graphs, blackboard, and others). The high-level comparison and mental model live in **[Patterns (concepts)](../concepts/patterns.md)** — start there.

## Practical shortcuts

- **Tool-heavy, exploratory loops** — default **ReAct**-style flows; good when the model must decide which tools to call and in what order.
- **Fixed pipelines** — prefer an explicit **sequential** (or compiled graph) layout when steps and branches are known up front.
- **LCEL callables as tools** — see **[LCEL as tools](lcel-as-tools.md)** when you want Runnable chains exposed like ordinary tools without rewriting them as `@tool` functions.

## Changing the pattern at runtime

The AGP command **`command.config.set`** accepts **`pattern`** (string). The web UI and CLI can bias routing without restarting the runtime when the agent supports live config updates.

## See also

- [Patterns](../concepts/patterns.md)
- [LCEL as tools](lcel-as-tools.md)
- [AGP protocol](../protocol/agp.md)
