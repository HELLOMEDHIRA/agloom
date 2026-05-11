# Fish completion for agloom — install:
#   agloom-completions fish > ~/.config/fish/completions/agloom.fish
# then `exec fish` or open a new terminal.

complete -c agloom -s h -l help -d 'Show help'
complete -c agloom -s V -l version -d 'Show version'
complete -c agloom -s t -l thread -d 'LangGraph thread id' -r
complete -c agloom -s s -l session -d 'AGP session id' -r
complete -c agloom -l store -d 'AGP EventStore' -xa 'none memory sqlite'
complete -c agloom -l store-path -d 'SQLite path for EventStore' -r
complete -c agloom -l diag -d 'Open diagnostic pane'
complete -c agloom -l no-cli-tools -d 'Omit CLI tools'
complete -c agloom -l no-shell-tool -d 'Disable shell tool'
complete -c agloom -l no-network-tools -d 'Disable network tools'
complete -c agloom -l unrestricted -d 'Disable CLI tool sandbox'
complete -c agloom -s m -l model -d 'LLM model id' -r
complete -c agloom -l provider -d 'Force provider' -r
complete -c agloom -l api-key-env -d 'Env var for API key' -r
complete -c agloom -s T -l temperature -d 'Sampling temperature' -r
complete -c agloom -l max-tokens -d 'Max output tokens' -r
complete -c agloom -l pattern -d 'Routing pattern' -r
complete -c agloom -l mcp -d 'MCP server spec' -r
complete -c agloom -l system-prompt -d 'System prompt' -r
complete -c agloom -l system-prompt-file -d 'System prompt file' -r
complete -c agloom -l no-memory -d 'Minimal session memory'
complete -c agloom -l memory -d 'Session memory type' -r
complete -c agloom -l memory-path -d 'SQLite path for memory' -r
complete -c agloom -l no-skills -d 'Disable skills disk mirror'
complete -c agloom -l skills-dir -d 'Skills directory' -r
complete -c agloom -l summarizer-model -d 'Summarizer model' -r
complete -c agloom -l no-auto-summarize -d 'Disable auto summarization'
complete -c agloom -l session-max-turns -d 'Session memory max turns' -r
complete -c agloom -l max-turns -d 'Alias for session-max-turns' -r
complete -c agloom -l prompt -d 'Direct prompt' -r
complete -c agloom -s q -l quiet -d 'Direct: stdout only'
complete -c agloom -l json -d 'Direct: JSONL AGP events'
complete -c agloom -l no-stream -d 'Direct: buffer until assistant'
complete -c agloom -l no-color -d 'Direct: strip ANSI'
complete -c agloom -l no-banner -d 'Suppress banner'
complete -c agloom -l auto-approve -d 'Direct: auto-approve HITL'
complete -c agloom -l auto-reject -d 'Direct: auto-reject HITL'
complete -c agloom -l hitl-tty -d 'Direct: interactive HITL'
complete -c agloom -l config -d 'Path to agloom.yaml' -r
complete -c agloom -l print-config -d 'Print merged config and exit'
complete -c agloom -l list-providers -d 'Print provider table'
complete -c agloom -l resolve-model -d 'Dry-run model resolution' -r
complete -c agloom -l multiline -d 'TUI: multiline compose'
complete -c agloom -l history-file -d 'Prompt history JSON' -r
