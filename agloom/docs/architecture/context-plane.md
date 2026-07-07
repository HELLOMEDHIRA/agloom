# Context Plane

The Context Plane assembles everything the model sees under an inferred token budget.

- Budget from `infer_context_window_tokens(model)`
- Large tool outputs → scratchpad + digest + `recall_tool_artifact`
- Over budget → structured summarization (never tail-chop)

Integrators do not configure trimming or `auto_summarize` toggles.
