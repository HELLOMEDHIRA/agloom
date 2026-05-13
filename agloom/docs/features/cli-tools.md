# Built-in CLI tools (`cli_tools`)

When you pass **`cli_tools=True`** or a **`cli_tools={...}`** dict to [`create_agent()`](../concepts/create-agent.md), agloom merges **built-in LangChain tools** bound to a sandboxed working directory. User-defined tools with the **same name** replace the builtin (last-write wins).

Runtime **`agloom-runtime serve --with-cli-tools`** enables the same toolkit for AGP sessions.

## Configuration (`cli_tools` dict)

All keys are optional when using a dict (defaults match `cli_tools=True`):

| Key             | Default | Meaning                                                                                                    |
| --------------- | ------- | ---------------------------------------------------------------------------------------------------------- |
| `working_dir`   | `"."`   | Root for relative paths and shell `cwd` (resolved to absolute).                                            |
| `allow_shell`   | `True`  | Expose `execute`, `bash`, and `bash_background*` tools.                                                    |
| `allow_network` | `True`  | Expose `fetch_url`, `read_url_markdown`, `web_search`.                                                     |
| `sandbox`       | `True`  | Restrict filesystem paths under `working_dir`; block obvious `..` escape.                                  |
| `task_tool`     | `True`  | Expose `task` (delegates to [`UnifiedAgent.adelegate`](../features/delegation.md)); requires `delegates=`. |

**SafetyContext** (internal) tracks **`recently_read_paths`** (for `write_file` / `notebook_edit` overwrite policy), **`background_shell_jobs`** (for `bash_background_*`), and the flags above.

## Filesystem & search

| Tool                                                         | Purpose                                                                            |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| `read_file(path, offset=0, limit=8000, line_numbers=True)`   | Read UTF-8 text; optional line prefixes; chunked via `offset`.                     |
| `write_file(path, content, force=False)`                     | Write text; existing files require prior `read_file` in-session or `force=True`.   |
| `edit_file(path, old_string, new_string, replace_all=False)` | First or all occurrences; atomic write.                                            |
| `multi_edit(path, edits_json)`                               | Ordered JSON array of `{old_string, new_string, replace_all?}`; atomic on success. |
| `glob_files(pattern, path=".")`                              | Sandbox glob; skips `.git`, `node_modules`, `__pycache__`, `.venv` segments.       |
| `delete_file(path)`                                          | Delete file only (not directories).                                                |
| `move_file(source_path, destination_path)`                   | Move/rename; registers destination for `write_file` policy.                        |
| `mkdir(path, parents=True, exist_ok=True)`                   | Create directory.                                                                  |
| `rmdir(path, recursive=False)`                               | Remove empty dir, or `recursive=True` for trees (sandboxed).                       |
| `list_dir(path=".")`                                         | Non-recursive listing.                                                             |
| `grep_files(pattern, path=".", max_matches=50)`              | Regex search; ripgrep fast path when available.                                    |

## Notebooks

| Tool                                            | Purpose                                                                                               |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `notebook_read(path, max_chars_per_cell=24000)` | Render `.ipynb` cells with indices and types (markdown/code/raw).                                     |
| `notebook_edit(path, edits_json, force=False)`  | Apply ops: `set_source`, `insert_cell`, `delete_cell` (see module docstrings); read-first or `force`. |

## Shell & PATH

| Tool                             | Purpose                                                                                                |
| -------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `which(executable)`              | `shutil.which` — **always** registered (works even when `allow_shell=False`).                          |
| `execute(command)`               | Argv split (`shell=False`); simple commands only.                                                      |
| `bash(command)`                  | Full shell (`shell=True`); each call is a fresh subshell (no persistent `cd`).                         |
| `bash_background(command)`       | Detached process; stdout/stderr discarded — redirect to a log file if needed. Returns `job_id`.        |
| `bash_background_status(job_id)` | Running vs exited + exit code.                                                                         |
| `bash_background_stop(job_id)`   | SIGTERM / terminate, then SIGKILL / kill after 2s if needed (POSIX uses process groups when possible). |

Shell tools are included in **`interrupt_before_tools`** by default when `allow_shell=True` (HITL gate).

## Web

| Tool                                                            | Purpose                                                                                                                |
| --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `fetch_url(url, max_bytes=512_000, extract_readable_text=True)` | HTTP GET; HTML → plain text when requested.                                                                            |
| `read_url_markdown(url, max_bytes=512_000)`                     | Fetch + readability extraction; uses **trafilatura** when `pip install 'agloom[readability]'`, else built-in stripper. |
| `web_search(query, max_results=5)`                              | Requires `AGLOOM_SEARCH_PROVIDER` (`searxng`, `tavily`, `brave`) and env keys per provider.                            |

## Meta & delegation

| Tool                               | Purpose                                                                      |
| ---------------------------------- | ---------------------------------------------------------------------------- |
| `ask_user(question, choices=None)` | HITL clarification over AGP (requires active bridge).                        |
| `write_todos(items_json)`          | Replace session todos; emits AGP `todos.updated` when an emitter is present. |
| `task(prompt, delegate_name=None)` | Blocking delegate to a **`delegates=`** target via `adelegate`.              |

## Names

The canonical set matches **`CLI_TOOL_NAMES`** in `agloom.cli_tools` (25 tools). Count may appear on **`runtime.ready`** as `cli_tools_count`.

## See also

- [Runtime CLI](../runtime/cli.md) — `agloom-runtime serve` flags (`--with-cli-tools`, `--cli-tools-*`).
- [HITL tool allowlist](hitl-allowlist.md) — persistent allowlist for gated tools.
