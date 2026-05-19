# Troubleshooting

## Cannot find `agloom-runtime`

**Fix:** `pip install agloom` (Python 3.12+). Optionally set **`AGLOOM_RUNTIME`** to the full path of the installed script or interpreter wrapper.

## No API key found / model resolution fails

Run:

```bash
agloom --list-providers
```

Pick a provider; export its env vars (see [Config & environment](config.md)) or use **`--api-key-env`**.

## `langchain-*` / optional extra missing

Messages look like:

```text
langchain-groq not installed. Run: pip install 'agloom[groq]'
```

**Fix:** install the suggested extra (combine extras: `pip install 'agloom[groq,openai]'`).

## Unknown provider / typo

```text
unknown provider 'gorq' — did you mean 'groq'? Run `agloom --list-providers`.
```

**Fix:** correct the slug or run **`agloom --resolve-model "<your string>"`** for a dry-run trace.

## Model id rejected upstream

The resolver succeeded locally but the vendor API returns 404 / invalid model.

**Fix:** copy a current model id from the provider’s catalog ([Models](models.md) links).

## Tool always prompts despite “allowlist”

**Fix:** confirm **`.agloom/hitl_tool_allowlist.json`** exists on cwd used by the runtime, paths match **`--hitl-allowlist-path`**, and you chose **allowlist** (not one-shot approve) in the UI.

## `EACCES` / writes fail

**Fix:** check **`--cli-tools-working-dir`** / sandbox — writes outside the sandbox root are blocked unless **`--unrestricted`**.

## WebSocket / bridge disconnect

The npm CLI uses **stdio** only. If stdout corrupts NDJSON (filters, accidental binary), the bridge drops lines.

**Fix:** avoid piping stdout through tools that strip newlines; use **`--quiet`** / **`--json`** deliberately.

## Token / cost looks wrong

Some providers omit usage metadata on streamed chunks.

**Fix:** use **`metric.tokens`** for rollups (status bar / `/cost`), not a naive sum of every **`token.delta`**. Upgrade the LangChain integration package if totals stay zero; fall back to provider dashboards.

Display format in the TUI is typically **`↑input ↓output`** when both directions are present.

## Assistant shows raw tool JSON instead of prose

After HITL or a tool-heavy turn, you may see `{"name":"read_file",…}` in the transcript if the client only rendered streamed deltas.

**Fix:** prefer **`message.assistant`** `data.content` as the final answer; strip `[agloom:tool_result]` envelopes. Rebuild the CLI after pulling UI fixes: `cd agloom_cli && npm run build`. See [AGP wire reference](reference.md#assistant-text-wire-vs-stream).

## Tool output looks cut off

Tool rows should show the full **`tool.call.result`** `output_preview`. If you use a custom client, do not cap preview text unless you set `truncated: true` handling yourself.

## Vertex / Bedrock auth errors

**Fix:** follow cloud IAM paths ([Models](models.md)): `aws configure` / IAM roles for Bedrock; `gcloud auth application-default login` or service-account JSON for Vertex.
