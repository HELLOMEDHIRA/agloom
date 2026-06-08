# Bash completion for agloom (agloom-cli). Source from ~/.bashrc:
#   source /path/to/agloom_cli/completions/agloom.bash
# or copy this file to /etc/bash_completion.d/agloom

_agloom() {
  local cur prev words cword
  _init_completion 2>/dev/null || {
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD - 1]}"
  }

  local opts="
    --help --version
    -t --thread -s --session
    --store --store-path --diag
    --no-cli-tools --no-shell-tool --no-network-tools --unrestricted
    -m --model --provider --api-key-env
    -T --temperature --max-tokens
    --mcp --system-prompt --system-prompt-file
    --memory --memory-path
    --skills-dir --summarizer-model --no-auto-summarize
    --session-max-turns --max-turns
    --prompt --quiet --json --no-stream --no-color --no-banner
    --auto-approve --auto-reject --hitl-tty
    --config --print-config
    --list-providers --resolve-model
    --history-file
  "

  mapfile -t COMPREPLY < <(compgen -W "${opts}" -- "${cur}")
}

complete -F _agloom agloom
