# Workload profiles

| Profile | strict | frozen | harness | Use case |
| --- | --- | --- | --- | --- |
| `interactive` (default) | no | no | optional | CLI chat |
| `tool_agent` | no | no | off | APIs, code |
| `harness_long` | yes | after seed | on | multi-day delivery |
| `platform_embedded` | yes | yes | on | embedded host app |
| `batch_frozen` | yes | yes | optional | batch classify |

```python
agent = await create_agent(model=llm, profile="platform_embedded", ...)
```

YAML (`agloom-runtime`):

```yaml
profile: interactive
```

Explicit kwargs override profile defaults.
