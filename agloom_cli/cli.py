"""agloom command-line interface."""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.theme import Theme

from .config import (
    config_source_fingerprints,
    ensure_config_ready,
    get_system_prompt,
    get_thread_id,
    list_project_cleanup_dirs,
    load_config,
    normalize_cli_session_id,
    remove_project_cleanup_dirs,
    resolve_model,
    session_record_path,
    set_cli_project_root,
    start_new_session,
    storage_dir,
)
from .mcp_loader import build_mcp_configs
from .model_resolver import MissingProviderApiKey, MissingProviderDependency, describe_llm
from .project import detect_project, get_git_info
from .project_rules import load_project_rules
from .repl import render_banner, run_shell
from .session_manager import get_session_context_summary, update_session_file_summaries
from .tool_loader import discover_tools

console = Console(
    theme=Theme(
        {
            "info": "cyan",
            "warning": "yellow",
            "error": "red bold",
            "success": "green",
            "path": "blue",
        }
    )
)

app = typer.Typer(
    name="agloom",
    help="AI programming assistant with project awareness, smart context, learned best practices.",
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        from agloom_cli import __version__

        console.print(f"[success]agloom-cli[/success] version [info]{__version__}[/info]")
        raise typer.Exit()


def _get_builtin_tools() -> list:
    """Get built-in CLI tools."""
    from .tools import (
        clear_task_tracker,
        complete_step,
        copy_file,
        create_directory,
        create_task_plan,
        fetch_json,
        file_exists,
        find_docs,
        get_current_task,
        get_env_var,
        get_file_info,
        get_system_info,
        get_working_directory,
        http_delete,
        http_get,
        http_head,
        http_post,
        http_put,
        http_request,
        list_directory,
        list_env_vars,
        move_file,
        path_absolute,
        path_basename,
        path_exists,
        path_extension,
        path_is_directory,
        path_is_file,
        path_join,
        path_parent,
        path_stem,
        pop_working_directory,
        push_working_directory,
        read_file,
        remove_file,
        run_shell,
        run_shell_interactive,
        search_files,
        search_github,
        search_web,
        set_env_var,
        set_working_directory,
        show_remaining_steps,
        update_task_progress,
        web_search,
        write_file,
    )

    return [
        read_file,
        write_file,
        list_directory,
        file_exists,
        create_directory,
        remove_file,
        copy_file,
        move_file,
        get_file_info,
        search_files,
        run_shell,
        run_shell_interactive,
        get_system_info,
        get_env_var,
        set_env_var,
        list_env_vars,
        http_request,
        http_get,
        http_post,
        http_put,
        http_delete,
        http_head,
        fetch_json,
        web_search,
        search_web,
        find_docs,
        search_github,
        create_task_plan,
        get_current_task,
        complete_step,
        update_task_progress,
        show_remaining_steps,
        clear_task_tracker,
        get_working_directory,
        set_working_directory,
        push_working_directory,
        pop_working_directory,
        path_join,
        path_parent,
        path_absolute,
        path_exists,
        path_is_file,
        path_is_directory,
        path_basename,
        path_extension,
        path_stem,
    ]


@app.command(hidden=True)
def main(
    model: str = typer.Option("auto", "--model", "-m", help="Model ID"),
    name: str | None = typer.Option(None, "--name", help="Agent name"),
    system_prompt: str | None = typer.Option(None, "--system-prompt", help="System prompt"),
    tools_dir: Path | None = typer.Option(None, "--tools", "-t", help="Tools directory"),
    enable_memory: bool | None = typer.Option(None, "--memory/--no-memory", help="Enable memory"),
    memory_path: Path | None = typer.Option(None, "--memory-path", help="Memory storage path"),
    enable_skills: bool | None = typer.Option(None, "--skills/--no-skills", help="Enable skills"),
    max_skills: int | None = typer.Option(None, "--max-skills", help="Max skills"),
    session_max_turns: int | None = typer.Option(None, "--max-turns", help="Max session turns"),
    auto_summarize: bool | None = typer.Option(None, "--auto-summarize/--no-summarize", help="Auto-summarize"),
    summarize_threshold: int | None = typer.Option(None, "--summarize-threshold", help="Summarize threshold"),
    mcp_servers: str | None = typer.Option(None, "--mcp", help="MCP servers"),
    interrupt_before: str | None = typer.Option(None, "--interrupt-before", help="Interrupt before patterns"),
    interrupt_after: str | None = typer.Option(None, "--interrupt-after", help="Interrupt after patterns"),
    interrupt_before_tools: str | None = typer.Option(None, "--interrupt-before-tools", help="Interrupt before tools"),
    # Human approval
    require_approval: bool = typer.Option(
        False,
        "--require-approval",
        help="Require human approval for sensitive operations (shell, delete, write)",
    ),
    auto_approve_tools: str | None = typer.Option(
        None,
        "--auto-approve",
        help="Comma-separated tools to auto-approve (skip approval prompt)",
    ),
    max_concurrent: int | None = typer.Option(None, "--max-concurrent", help="Max concurrent workers"),
    max_retries: int | None = typer.Option(None, "--max-retries", help="Max retries"),
    retry_delay: float | None = typer.Option(None, "--retry-delay", help="Retry delay"),
    llm_timeout: float | None = typer.Option(None, "--llm-timeout", help="LLM timeout"),
    classifier_timeout: float | None = typer.Option(None, "--classifier-timeout", help="Classifier timeout"),
    fallback_pattern: str | None = typer.Option(None, "--fallback-pattern", help="Fallback pattern"),
    frozen: bool = typer.Option(False, "--frozen", help="Enable frozen mode"),
    frozen_template: str | None = typer.Option(None, "--frozen-template", help="Frozen template"),
    feedback_webhook: str | None = typer.Option(None, "--feedback-webhook", help="Feedback webhook"),
    cache_dir: Path | None = typer.Option(None, "--cache-dir", help="Cache directory"),
    config: Path | None = typer.Option(None, "--config", "-c", help="Config file"),
    session: str | None = typer.Option(None, "--session", "-s", help="Session ID to use"),
    strict_session: bool = typer.Option(
        False,
        "--strict-session",
        help="With --session: exit if sessions/<id>.json is missing (resume typo guard)",
    ),
    project: Path | None = typer.Option(None, "--project", "-p", help="Project directory (auto-detect context)"),
    rules_dir: Path | None = typer.Option(None, "--rules-dir", help="Custom rules directory (YAML files)"),
    refresh_rules: bool = typer.Option(False, "--refresh-rules", help="Force refresh project rules"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose"),
    no_builtins: bool = typer.Option(False, "--no-builtins", help="Disable built-in tools"),
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
    prompt: str | None = typer.Argument(None, help="Single prompt (if omitted, shell mode)"),
) -> None:
    asyncio.run(
        _run(
            model,
            name,
            system_prompt,
            tools_dir,
            enable_memory,
            memory_path,
            enable_skills,
            max_skills,
            session_max_turns,
            auto_summarize,
            summarize_threshold,
            mcp_servers,
            interrupt_before,
            interrupt_after,
            interrupt_before_tools,
            require_approval,
            auto_approve_tools,
            max_concurrent,
            max_retries,
            retry_delay,
            llm_timeout,
            classifier_timeout,
            fallback_pattern,
            frozen,
            frozen_template,
            feedback_webhook,
            cache_dir,
            config,
            session,
            strict_session,
            verbose,
            no_builtins,
            project,
            rules_dir,
            refresh_rules,
            prompt,
        )
    )


async def _run(
    model: str | None,
    name: str | None,
    system_prompt: str | None,
    tools_dir: Path | None,
    enable_memory: bool | None,
    memory_path: Path | None,
    enable_skills: bool | None,
    max_skills: int | None,
    session_max_turns: int | None,
    auto_summarize: bool | None,
    summarize_threshold: int | None,
    mcp_servers: str | None,
    interrupt_before: str | None,
    interrupt_after: str | None,
    interrupt_before_tools: str | None,
    require_approval: bool,
    auto_approve_tools: str | None,
    max_concurrent: int | None,
    max_retries: int | None,
    retry_delay: float | None,
    llm_timeout: float | None,
    classifier_timeout: float | None,
    fallback_pattern: str | None,
    frozen: bool,
    frozen_template: str | None,
    feedback_webhook: str | None,
    cache_dir: Path | None,
    config: Path | None,
    session: str | None,
    strict_session: bool,
    verbose: bool,
    no_builtins: bool,
    project: Path | None,
    rules_dir: Path | None,
    refresh_rules: bool,
    prompt: str | None,
) -> None:
    from agloom import LongTermStore, SessionMemory, create_agent
    from agloom.feedback.user_feedback import WebhookFeedbackHandler
    from agloom.models import PatternType

    # Detect project first so all config/session paths use <project>/.agloom
    project_ctx = detect_project(project)
    set_cli_project_root(project_ctx.root)

    # Ensure config is ready (auto-create if needed)
    ensure_config_ready()

    # ASCII banner first for both one-shot and interactive (Super-Brain / logs come after).
    console.print(render_banner("AGLOOM"))
    console.print()

    cfg = load_config(config) if config else load_config(None)

    # Super-Brain: required local graph + MCP — always run init for this project root
    from . import superbrain_setup

    if not superbrain_setup.agsuperbrain_installed():
        console.print(
            "[error]agsuperbrain is required for the agloom CLI but is not importable.[/error]\n"
            "  [dim]Reinstall: pip install -U agloom[/dim]"
        )
        raise typer.Exit(1)
    init_code = superbrain_setup.run_agsuperbrain_init(project_ctx.root, quiet=not verbose)
    if init_code != 0:
        console.print(
            f"[error]agsuperbrain init failed (exit {init_code}). Fix the project or Super-Brain setup.[/error]"
        )
        raise typer.Exit(init_code)

    # Load project rules
    rules_config = cfg.get("rules", {})
    config_rules_dir = rules_config.get("dir")
    rules_force_refresh = refresh_rules or rules_config.get("refresh", False)

    rules = None
    if rules_dir or config_rules_dir:
        rules = load_project_rules(
            project_ctx.root,
            rules_dir or (Path(config_rules_dir) if config_rules_dir else None),
            force_refresh=rules_force_refresh,
        )
    else:
        rules = load_project_rules(
            project_ctx.root,
            force_refresh=rules_force_refresh,
        )

    project_rules = rules.get_relevant_rules(prompt or "general") if rules else ""

    # Get model - check config AI section
    ai_config = cfg.get("ai", {})
    config_model = ai_config.get("model", "auto")
    try:
        llm = resolve_model(model or config_model)
    except MissingProviderDependency as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1) from None
    except MissingProviderApiKey as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1) from None
    if llm is None:
        console.print(
            "[error]No model configured. Set an API key for a supported provider (e.g. OPENAI_API_KEY, "
            "GROQ_API_KEY, GOOGLE_API_KEY) and install the matching extra (e.g. pip install 'agloom[groq]').[/error]"
        )
        raise typer.Exit(1)

    # Get or create session (--session flag overrides config/auto-generated ID)
    try:
        if session is not None:
            thread_id = normalize_cli_session_id(session)
        else:
            thread_id = get_thread_id(cfg)
    except ValueError as exc:
        console.print(f"[error]Invalid session id:[/error] {exc}")
        raise typer.Exit(1) from None

    session_json = session_record_path(thread_id)
    if session is not None:
        if not session_json.exists():
            msg = (
                f"No session record at [path]{session_json}[/path] — "
                "nothing to resume on disk; a new session file will be created for this id."
            )
            if strict_session:
                console.print(f"[error]{msg}[/error]")
                raise typer.Exit(1)
            console.print(f"[warning]{msg}[/warning]")
    elif os.environ.get("AGLOOM_THREAD_ID") and not session_json.exists():
        console.print(
            f"[warning]AGLOOM_THREAD_ID is set but there is no session file yet at "
            f"[path]{session_json.name}[/path]; it will be created on this run.[/warning]"
        )

    agent_name = name or ai_config.get("name", "agloom")
    prov, mid = describe_llm(llm)
    sources = config_source_fingerprints(config)
    bundle = "|".join(f"{s['path']}:{s['sha256']}" for s in sources)
    bundle_hash = hashlib.sha256(bundle.encode()).hexdigest() if bundle else ""
    cli_payload: dict[str, Any] = {}
    if model is not None:
        cli_payload["model"] = model
    if config is not None:
        cli_payload["config"] = str(config)
    if name is not None:
        cli_payload["name"] = name
    if session is not None:
        cli_payload["session"] = thread_id
    run_meta = {
        "at": datetime.now(UTC).isoformat(),
        "project_root": str(project_ctx.root.resolve()),
        "config_bundle_sha256": bundle_hash,
        "config_sources": sources,
        "cli": cli_payload,
        "resolved": {"model": f"{prov}:{mid}", "agent_name": agent_name},
    }
    start_new_session(thread_id, run_metadata=run_meta)

    tools = []
    if not no_builtins:
        tools.extend(_get_builtin_tools())
    if tools_dir or cfg.get("tools", {}).get("dir"):
        tools.extend(discover_tools(tools_dir or cfg.get("tools", {}).get("dir")))

    # MCP servers (Super-Brain preset, server_list, legacy comma-separated — see mcp_loader.build_mcp_configs)
    mcp_configs = build_mcp_configs(cfg, mcp_servers)
    base_system_prompt = system_prompt or ai_config.get("system_prompt") or get_system_prompt()

    # Get session context for smart injection
    session_context = get_session_context_summary(
        {
            "project_structure": {
                "root": str(project_ctx.root),
                "language": project_ctx.language,
                "frameworks": project_ctx.frameworks,
            }
        }
    )

    # Append session context and project rules to system prompt
    prompt_parts = [base_system_prompt]

    if session_context:
        prompt_parts.append("\n## Current Session Context\n")
        prompt_parts.append(session_context)

    if project_rules:
        prompt_parts.append("\n")
        prompt_parts.append(project_rules)

    agent_system_prompt = "".join(prompt_parts)

    # Update file summaries for session
    if thread_id:
        update_session_file_summaries(thread_id, str(project_ctx.root))

    # Memory configuration
    memory_config = cfg.get("memory", {})
    memory_path = memory_path or cfg.get("memory_path")
    enable_memory = enable_memory if enable_memory is not None else memory_config.get("enabled", True)
    session_max_turns = session_max_turns if session_max_turns else memory_config.get("max_turns", 50)
    auto_summarize = auto_summarize if auto_summarize is not None else cfg.get("auto_summarize", True)
    summarize_threshold = summarize_threshold or cfg.get("summarize_threshold", 200000)

    # Skills configuration
    skills_config = cfg.get("skills", {})
    enable_skills = enable_skills if enable_skills is not None else skills_config.get("enabled", True)
    max_skills = max_skills or skills_config.get("max_skills", 30)

    # Execution configuration
    execution_config = cfg.get("execution", {})
    max_concurrent = max_concurrent or execution_config.get("max_concurrent", 4)
    max_retries = max_retries or execution_config.get("max_retries", 2)
    retry_delay = retry_delay or execution_config.get("retry_delay", 1.0)
    llm_timeout = llm_timeout or execution_config.get("llm_timeout", 120.0)
    classifier_timeout = classifier_timeout or execution_config.get("classifier_timeout", 30.0)

    # Safety configuration
    safety_config = cfg.get("safety", {})
    frozen = frozen or cfg.get("frozen", False)
    frozen_template = frozen_template or cfg.get("frozen_template")
    feedback_webhook = feedback_webhook or cfg.get("feedback_webhook")
    cache_dir = cache_dir or cfg.get("cache_dir")
    interrupt_before = interrupt_before or cfg.get("interrupt_before")
    interrupt_after = interrupt_after or cfg.get("interrupt_after")
    interrupt_before_tools = interrupt_before_tools or cfg.get("interrupt_before_tools")
    require_approval = require_approval or safety_config.get("require_approval", False)
    auto_approve_tools = auto_approve_tools or safety_config.get("auto_approve", "")

    # Human approval callback
    user_callback = None
    if require_approval:
        from .hitl import create_user_callback

        auto_list = [t.strip() for t in auto_approve_tools.split(",")] if auto_approve_tools else []
        user_callback = create_user_callback(auto_approve_tools=auto_list)
        console.print("[yellow]Human approval enabled for sensitive operations[/yellow]")

    feedback_handler = query_cache = None

    if feedback_webhook:
        try:
            feedback_handler = WebhookFeedbackHandler(url=feedback_webhook)
        except Exception as e:
            console.print(f"[warning]Feedback webhook error: {e}")

    if cache_dir:
        try:
            from langchain_huggingface import HuggingFaceEmbeddings

            from agloom import create_cache

            embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
            query_cache = create_cache(embeddings)
        except ImportError:
            console.print(
                "[warning]Cache needs HuggingFaceEmbeddings from langchain-huggingface "
                "(normally installed with agloom): pip install langchain-huggingface[/warning]"
            )
        except Exception as e:
            console.print(f"[warning]Cache error: {e}")

    from agloom.skills.registry import set_extra_skill_dirs

    from .persistence import cli_langgraph_sqlite

    async with cli_langgraph_sqlite(enable_memory, storage_dir()) as (checkpointer, shared_graph_store):
        memory = None
        store = None
        if enable_memory:
            store = LongTermStore(shared_graph_store)
            memory = SessionMemory(
                store=shared_graph_store,
                max_turns=session_max_turns,
                auto_summarize=auto_summarize,
                summarize_threshold=summarize_threshold,
                summarizer_model=llm,
            )

        if enable_skills and store is not None:
            set_extra_skill_dirs([str((storage_dir() / "skills").resolve())])
        else:
            set_extra_skill_dirs([])

        fallback = PatternType(fallback_pattern.upper()) if fallback_pattern else None

        agent_config = {
            "model": llm,
            "name": agent_name,
            "tools": tools,
            "system_prompt": agent_system_prompt,
            "memory": memory,
            "store": store,
            "checkpointer": checkpointer,
            "mcp_servers": mcp_configs if mcp_configs is not None else [],
            "debug": verbose,
            "enable_memory_tools": enable_memory,
            "user_callback": user_callback,
            "interrupt_before_tools": (
                [t.strip() for t in interrupt_before_tools.split(",")]
                if interrupt_before_tools
                else ["run_shell", "write_file", "remove_file"]
                if require_approval
                else None
            ),
            "max_concurrent": max_concurrent,
            "max_retries": max_retries,
            "retry_delay": retry_delay,
            "llm_timeout": llm_timeout,
            "classifier_timeout": classifier_timeout,
            "session_max_turns": session_max_turns,
            "auto_summarize": auto_summarize,
            "summarize_threshold": summarize_threshold,
            "max_skills": max_skills if enable_skills else 0,
            "feedback_handler": feedback_handler,
            "fallback_pattern": fallback,
            "interrupt_before": [p.strip() for p in interrupt_before.split(",")] if interrupt_before else None,
            "interrupt_after": [p.strip() for p in interrupt_after.split(",")] if interrupt_after else None,
            "query_cache": query_cache,
            "frozen": frozen,
            "frozen_template": frozen_template,
            "skills_disk_mirror": (storage_dir() / "skills")
            if (enable_skills and store is not None)
            else None,
        }

        agent_kwargs: Any = agent_config

        if prompt:
            agent = await create_agent(**agent_kwargs)
            result = await agent.ainvoke(prompt, thread_id=thread_id)
            console.print(result.output)
        else:
            git_info = get_git_info(project_ctx.root)

            console.print("[success]agloom shell[/success] — type 'exit' to quit")
            console.print(f"Model: [info]{model or config_model}[/info]")
            console.print(f"Tools: [info]{len(tools)}[/info]")
            if enable_memory:
                console.print("[info]Memory: enabled (SQLite resume under .agloom)[/info]")
            if enable_skills:
                console.print(f"[info]Skills: enabled (max: {max_skills})[/info]")

            console.print()
            if project_ctx.language != "unknown":
                console.print(f"[dim]Project:[/dim] [path]{project_ctx.root}[/path]")
                console.print(f"[dim]Language:[/dim] [info]{project_ctx.language}[/info]", end="")
                if project_ctx.frameworks:
                    console.print(f" [dim]({', '.join(project_ctx.frameworks)})[/dim]")
                else:
                    console.print()
                if project_ctx.project_type != "library":
                    console.print(f"[dim]Type:[/dim] [warning]{project_ctx.project_type}[/warning]")
                if git_info.get("branch"):
                    console.print(f"[dim]Git:[/dim] [success]{git_info['branch']}[/success]", end="")
                    if git_info.get("status") == "dirty":
                        console.print(" [warning]dirty[/warning]")
                    else:
                        console.print()
            console.print()
            agent = await create_agent(**agent_kwargs)
            await run_shell(agent, verbose=verbose, llm_status=f"{prov}:{mid}", thread_id=thread_id)


@app.command("clean")
def clean_cmd(
    project: Path | None = typer.Option(
        None,
        "--project",
        "-p",
        help="Project root (default: auto-detect from current directory)",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Delete without confirmation",
    ),
) -> None:
    """Remove ``.agloom`` and ``.agsuperbrain`` from the project (config, caches, Super-Brain index)."""
    project_ctx = detect_project(project)
    root = project_ctx.root
    targets = list_project_cleanup_dirs(root)
    if not targets:
        console.print("[dim]Nothing to remove — no .agloom or .agsuperbrain directory here.[/dim]")
        raise typer.Exit(0)

    console.print("[warning]This will permanently delete:[/warning]")
    for t in targets:
        console.print(f"  [path]{t}[/path]")
    if not yes and not typer.confirm("Delete these directories?", default=False):
        console.print("[dim]Cancelled.[/dim]")
        raise typer.Exit(0)

    removed = remove_project_cleanup_dirs(root)
    for t in removed:
        console.print(f"[success]Removed[/success] {t}")


@app.command("refresh-rules")
def refresh_rules_cmd(project: Path | None = None) -> None:
    """Force refresh project rules."""
    from .project_rules import load_project_rules

    project_ctx = detect_project(project)
    set_cli_project_root(project_ctx.root)
    rules = load_project_rules(project_ctx.root, force_refresh=True)

    console.print(f"[success]Rules refreshed for:[/success] {project_ctx.root}")
    console.print(f"[dim]Source:[/dim] {rules.source_file}")
    console.print(f"[dim]Framework:[/dim] {rules.analysis.get('framework', 'unknown')}")
    console.print(f"[dim]Test:[/dim] {rules.analysis.get('test_framework', 'unknown')}")


_SUBCOMMANDS = frozenset({"main", "refresh-rules", "clean"})


def run_cli() -> None:
    import sys

    argv = sys.argv[1:]
    if (not argv) or (argv[0] not in _SUBCOMMANDS and argv[0] not in ("-h", "--help")):
        sys.argv.insert(1, "main")
    app()


if __name__ == "__main__":
    run_cli()
