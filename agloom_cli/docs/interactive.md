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
- **Ctrl+X** — cancel current run (same idea as `/cancel`). The input field ignores this chord so **x** is not inserted.
- **Ctrl+T** — expand/collapse tool rows for the active turn (same as `/tools`).
- **Slash hints** — when your message starts with `/`, matching commands are listed under the input as you type (no separate Tab overlay).

Navigation follows common terminal conventions (focusable regions, overlays, and readline-style input where applicable).

## Slash commands

Typed at the input bar. The list below matches what **`/help`** shows in the UI.

| Command              | Action                                                 |
| -------------------- | ------------------------------------------------------ |
| `/help`              | Full list in-modal                                     |
| `/cancel`            | Cancel current run (**Ctrl+X**)                        |
| `/clear`             | Clear transcript + metrics notes                       |
| `/undo`              | Undo last turn (pops last user message from memory)    |
| `/retry`             | Re-run the last completed turn                         |
| `/checkpoint [name]` | Create a named git checkpoint (requires harness)       |
| `/diff [path]`       | Show git diff for working tree (requires harness)      |
| `/hint`              | Suggest git revert hint (requires harness)               |
| `/git status`        | Show working tree status (requires harness)             |
| `/git checkpoints`   | List named checkpoints (requires harness)               |
| `/plan <goal>`       | Preview how the agent would decompose a goal           |
| `/model`             | Show active model from runtime/metrics                 |
| `/memory clear`      | Clear session memory for current thread                |
| `/cost`              | Token/cost slice + recent metrics                      |
| `/pattern <name>`    | Send `command.config.set` pattern                      |
| `/temperature <n>`   | Set temperature via config                             |
| `/system <text>`     | Inline system prompt update                            |
| `/session list`      | List sessions (**requires `--store`** on runtime)      |
| `/diag`              | Toggle stderr diagnostic pane                          |
| `/stats`             | Toggle metrics sidebar                                 |
| `/tools`             | Toggle expand/collapse for all tool results            |
| `/budget raise …`    | Raise token/USD caps (`--tokens N`, `--usd N`)        |
| `/feedback <1-5>`    | Score last completed turn                              |
| `/save <path.md>`    | Export transcript as Markdown to disk                  |
| `/exit`, `/quit`     | Shutdown runtime and exit                              |

Many AGP events append short lines under **Wire notes** (config applied, sessions, feedback, …).

## Live model switch

Use **`/model`** for visibility; actual model changes go through **`command.config.set`** with a new `model_id` when wired from the UI (same mechanism as `--model` at boot).

## See also

- [Flags](flags.md) — `--diag`, `--thread`, `--session`
- [AGP wire reference](reference.md) — stdout/stderr protocol rules
