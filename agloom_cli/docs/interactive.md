# Interactive UI (TUI)

Running **`agloom`** without a one-shot prompt (and with stdin as a TTY) opens the **Ink** fullscreen UI. It renders AGP events as transcript cards, metrics, and optional diagnostics.

## Layout

- **Main pane** — active turn (streaming assistant + tool traces) and completed turn history.
- **Status bar** — session/thread hints, model label, token/cost summaries when available (from runtime metrics).
- **Metrics sidebar** (`/stats`) — structured counters and **Wire notes** (one-line AGP highlights).
- **Diagnostic pane** (`--diag` or `/diag`) — **`agloom-runtime` stderr** (Python logs), kept off stdout so AGP stays parseable.

## Banner

On startup the CLI may print a compact **banner** to stderr (version line). Suppress with **`--no-banner`** or set **`AGLOOM_BANNER`** to `0` / `false`.

## Hotkeys & flow

- **Esc** — cancel inline overlays where applicable.
- **Ctrl+C** — shutdown sequence (runtime exit).
- **Ctrl+X** — cancel current run (same idea as `/cancel`).
- **Tab** — opens slash-command autocomplete overlay.

Exact bindings follow Ink focus and input handlers in the running app.

## Slash commands

Typed at the input bar. The list below matches what **`/help`** shows in the UI.

| Command | Action |
| --- | --- |
| `/help` | Full list in-modal |
| `/cancel` | Cancel current run (**Ctrl+X**) |
| `/clear` | Clear transcript + metrics notes |
| `/model` | Show active model from runtime/metrics |
| `/memory clear` | Clear session memory for current thread |
| `/cost` | Token/cost slice + recent metrics |
| `/pattern <name>` | Send `command.config.set` pattern |
| `/temperature <n>` | Set temperature via config |
| `/system <text>` | Inline system prompt update |
| `/session list` | List sessions (**requires `--store`** on runtime) |
| `/diag` | Toggle stderr diagnostic pane |
| `/stats` | Toggle metrics sidebar |
| `/feedback <1-5>` | Score last completed turn |
| `/exit`, `/quit` | Shutdown runtime and exit |

Many AGP events append short lines under **Wire notes** (config applied, sessions, feedback, …).

## Live model switch

Use **`/model`** for visibility; actual model changes go through **`command.config.set`** with a new `model_id` when wired from the UI (same mechanism as `--model` at boot).

## See also

- [Flags](flags.md) — `--diag`, `--thread`, `--session`
- [AGP wire reference](reference.md) — stdout/stderr protocol rules
