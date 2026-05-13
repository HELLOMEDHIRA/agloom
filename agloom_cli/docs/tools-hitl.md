# Built-in CLI tools & HITL

When CLI tools are enabled (npm default → **`agloom-runtime --with-cli-tools`** with working directory = current cwd), the agent receives **sandboxed** filesystem, shell, network, and meta tools — the same **`cli_tools`** toolkit documented for [`create_agent`](../agloom/concepts/create-agent.md).

## What gets injected

There are **25** canonical built-in tools. Categories:

- **Filesystem & search** — `read_file`, `write_file`, `edit_file`, `glob_files`, `grep_files`, `list_dir`, …
- **Notebooks** — `notebook_read`, `notebook_edit`
- **Shell** — `execute`, `bash`, `bash_background*` (optional), plus `which`
- **Web** — `fetch_url`, `read_url_markdown`, `web_search` (when network allowed)
- **Meta** — `ask_user`, `write_todos`, `task` (delegation)

Full tables: [Built-in CLI tools](../agloom/features/cli-tools.md).

## npm / runtime flags

| npm flag             | Runtime flag             |
| -------------------- | ------------------------ |
| `--no-cli-tools`     | Omit `--with-cli-tools`  |
| `--no-shell-tool`    | `--cli-tools-no-shell`   |
| `--no-network-tools` | `--cli-tools-no-network` |
| `--unrestricted`     | `--cli-tools-no-sandbox` |

Working directory root defaults to the directory where you launched **`agloom`**.

## HITL (human-in-the-loop)

Some tools run **before** completion until you approve or deny — especially destructive or shell/network actions. Details and policy tables: [Human-in-the-Loop](../agloom/features/hitl.md).

**Quiet reads** (`read_file`, `glob_files`, `grep`, `fetch_url`, `web_search` under typical configs) usually **do not** interrupt; writes, shell, and similar actions **do** by default.

### Allowlist persistence

Approvals can be remembered in **`.agloom/hitl_tool_allowlist.json`** (wire decision **allowlist**). Override path via runtime **`--hitl-allowlist-path`** or disable persistence with **`--no-hitl-allowlist-persist`** (see [Runtime CLI](../agloom/runtime/cli.md)).

### Mid-session prompts

In the TUI, approval UI presents choices; **`y`** may accept once while **`a`** (when offered) allowlists the tool name persistently — exact UX depends on the AGP HITL bridge.

### Direct mode reminder

Default non-TTY behavior often **auto-rejects** gates unless **`--auto-approve`**, **`--auto-reject`**, or **`--hitl-tty`** is set. See [Direct mode](direct-mode.md).

## Clarifications

`ask_user` delivers **free-text** or choice prompts over AGP — respond in the client when the bridge asks.

## Further reading

- [HITL tool allowlist](../agloom/features/hitl-allowlist.md)
- [CLI tools feature doc](../agloom/features/cli-tools.md)
