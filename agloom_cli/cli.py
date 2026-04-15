"""CLI entry point — shell mode by default like opencode/claude code."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.theme import Theme

from .config import load_config, resolve_model, get_thread_id
from .repl import run_shell
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
    help="The intelligent fabric for AI agents — 9 execution patterns, auto-classified.",
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


@app.command()
def main(
    model: Optional[str] = typer.Option("auto", "--model", "-m", help="Model ID"),
    name: Optional[str] = typer.Option(None, "--name", help="Agent name"),
    system_prompt: Optional[str] = typer.Option(None, "--system-prompt", help="System prompt"),
    tools_dir: Optional[Path] = typer.Option(None, "--tools", "-t", help="Tools directory"),
    enable_memory: bool = typer.Option(True, "--memory/--no-memory", help="Enable memory"),
    memory_path: Optional[Path] = typer.Option(None, "--memory-path", help="Memory storage path"),
    enable_skills: bool = typer.Option(True, "--skills/--no-skills", help="Enable skills"),
    max_skills: int = typer.Option(30, "--max-skills", help="Max skills"),
    session_max_turns: int = typer.Option(20, "--max-turns", help="Max session turns"),
    auto_summarize: bool = typer.Option(True, "--auto-summarize/--no-summarize", help="Auto-summarize"),
    summarize_threshold: int = typer.Option(200000, "--summarize-threshold", help="Summarize threshold"),
    mcp_servers: Optional[str] = typer.Option(None, "--mcp", help="MCP servers"),
    interrupt_before: Optional[str] = typer.Option(None, "--interrupt-before", help="Interrupt before patterns"),
    interrupt_after: Optional[str] = typer.Option(None, "--interrupt-after", help="Interrupt after patterns"),
    interrupt_before_tools: Optional[str] = typer.Option(
        None, "--interrupt-before-tools", help="Interrupt before tools"
    ),
    # Human approval
    require_approval: bool = typer.Option(
        False,
        "--require-approval",
        help="Require human approval for sensitive operations (shell, delete, write)",
    ),
    auto_approve_tools: Optional[str] = typer.Option(
        None,
        "--auto-approve",
        help="Comma-separated tools to auto-approve (skip approval prompt)",
    ),
    max_concurrent: int = typer.Option(4, "--max-concurrent", help="Max concurrent workers"),
    max_retries: int = typer.Option(2, "--max-retries", help="Max retries"),
    retry_delay: float = typer.Option(1.0, "--retry-delay", help="Retry delay"),
    llm_timeout: float = typer.Option(120.0, "--llm-timeout", help="LLM timeout"),
    classifier_timeout: float = typer.Option(30.0, "--classifier-timeout", help="Classifier timeout"),
    fallback_pattern: Optional[str] = typer.Option(None, "--fallback-pattern", help="Fallback pattern"),
    frozen: bool = typer.Option(False, "--frozen", help="Enable frozen mode"),
    frozen_template: Optional[str] = typer.Option(None, "--frozen-template", help="Frozen template"),
    feedback_webhook: Optional[str] = typer.Option(None, "--feedback-webhook", help="Feedback webhook"),
    cache_dir: Optional[Path] = typer.Option(None, "--cache-dir", help="Cache directory"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Config file"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose"),
    no_builtins: bool = typer.Option(False, "--no-builtins", help="Disable built-in tools"),
    version: bool = typer.Option(False, "--version", help="Show version", callback=_version_callback),
    prompt: Optional[str] = typer.Argument(None, help="Single prompt (if omitted, shell mode)"),
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
            verbose,
            no_builtins,
            prompt,
        )
    )


async def _run(
    model: Optional[str],
    name: Optional[str],
    system_prompt: Optional[str],
    tools_dir: Optional[Path],
    enable_memory: bool,
    memory_path: Optional[Path],
    enable_skills: bool,
    max_skills: int,
    session_max_turns: int,
    auto_summarize: bool,
    summarize_threshold: int,
    mcp_servers: Optional[str],
    interrupt_before: Optional[str],
    interrupt_after: Optional[str],
    interrupt_before_tools: Optional[str],
    require_approval: bool,
    auto_approve_tools: Optional[str],
    max_concurrent: int,
    max_retries: int,
    retry_delay: float,
    llm_timeout: float,
    classifier_timeout: float,
    fallback_pattern: Optional[str],
    frozen: bool,
    frozen_template: Optional[str],
    feedback_webhook: Optional[str],
    cache_dir: Optional[Path],
    config: Optional[Path],
    verbose: bool,
    no_builtins: bool,
    prompt: Optional[str],
) -> None:
    from agloom import create_agent, SessionMemory, LongTermStore
    from agloom.models import MCPServerConfig, PatternType
    from agloom.feedback.user_feedback import WebhookFeedbackHandler
    from langgraph.checkpoint.memory import MemorySaver

    cfg = {}
    if config:
        cfg = load_config(config)

    llm = resolve_model(model or cfg.get("model", "auto"))
    if llm is None:
        console.print("[error]No model configured.[/error]")
        raise typer.Exit(1)

    thread_id = get_thread_id(cfg)

    tools = []
    if not no_builtins:
        tools.extend(_get_builtin_tools())
    if tools_dir or cfg.get("tools_dir"):
        tools.extend(discover_tools(tools_dir or cfg.get("tools_dir")))

    mcp_servers_list = mcp_servers or cfg.get("mcp_servers", "")
    mcp_configs = [MCPServerConfig(name=s.strip()) for s in mcp_servers_list.split(",")] if mcp_servers_list else []

    agent_name = name or cfg.get("name", "agloom-shell")
    agent_system_prompt = system_prompt or cfg.get("system_prompt")

    memory_path = memory_path or cfg.get("memory_path")
    enable_memory = enable_memory if enable_memory != True else cfg.get("enable_memory", True)
    enable_skills = enable_skills if enable_skills != True else cfg.get("enable_skills", True)
    max_skills = max_skills if max_skills != 30 else cfg.get("max_skills", 30)
    session_max_turns = session_max_turns if session_max_turns != 20 else cfg.get("session_max_turns", 20)
    auto_summarize = auto_summarize if auto_summarize != True else cfg.get("auto_summarize", True)
    summarize_threshold = (
        summarize_threshold if summarize_threshold != 200000 else cfg.get("summarize_threshold", 200000)
    )
    max_concurrent = max_concurrent if max_concurrent != 4 else cfg.get("max_concurrent", 4)
    max_retries = max_retries if max_retries != 2 else cfg.get("max_retries", 2)
    retry_delay = retry_delay if retry_delay != 1.0 else cfg.get("retry_delay", 1.0)
    llm_timeout = llm_timeout if llm_timeout != 120.0 else cfg.get("llm_timeout", 120.0)
    classifier_timeout = classifier_timeout if classifier_timeout != 30.0 else cfg.get("classifier_timeout", 30.0)
    frozen = frozen or cfg.get("frozen", False)
    frozen_template = frozen_template or cfg.get("frozen_template")
    feedback_webhook = feedback_webhook or cfg.get("feedback_webhook")
    cache_dir = cache_dir or cfg.get("cache_dir")
    interrupt_before = interrupt_before or cfg.get("interrupt_before")
    interrupt_after = interrupt_after or cfg.get("interrupt_after")
    interrupt_before_tools = interrupt_before_tools or cfg.get("interrupt_before_tools")

    # Human approval callback
    user_callback = None
    if require_approval:
        from .hitl import create_user_callback

        auto_list = [t.strip() for t in auto_approve_tools.split(",")] if auto_approve_tools else []
        user_callback = create_user_callback(auto_approve=auto_list)
        console.print("[yellow]Human approval enabled for sensitive operations[/yellow]")

    memory = store = checkpointer = feedback_handler = query_cache = None

    if enable_memory:
        store = LongTermStore(str(memory_path)) if memory_path and memory_path.exists() else LongTermStore()
        checkpointer = MemorySaver()
        memory = SessionMemory(
            store=store,
            max_turns=session_max_turns,
            auto_summarize=auto_summarize,
            summarize_threshold=summarize_threshold,
            summarizer_model=llm,
        )

    if feedback_webhook:
        try:
            feedback_handler = WebhookFeedbackHandler(webhook_url=feedback_webhook)
        except Exception as e:
            console.print(f"[warning]Feedback webhook error: {e}")

    if cache_dir:
        try:
            from agloom import create_cache

            query_cache = create_cache(str(cache_dir))
        except Exception as e:
            console.print(f"[warning]Cache error: {e}")

    fallback = PatternType(fallback_pattern.upper()) if fallback_pattern else None

    agent_config = dict(
        model=llm,
        name=agent_name,
        tools=tools,
        system_prompt=agent_system_prompt,
        memory=memory,
        store=store,
        checkpointer=checkpointer,
        mcp_servers=mcp_configs if mcp_configs else None,
        debug=verbose,
        enable_memory_tools=enable_memory,
        user_callback=user_callback,
        interrupt_before_tools=(
            [t.strip() for t in interrupt_before_tools.split(",")]
            if interrupt_before_tools
            else ["run_shell", "write_file", "remove_file"]
            if require_approval
            else None
        ),
        max_concurrent=max_concurrent,
        max_retries=max_retries,
        retry_delay=retry_delay,
        llm_timeout=llm_timeout,
        classifier_timeout=classifier_timeout,
        session_max_turns=session_max_turns,
        auto_summarize=auto_summarize,
        summarize_threshold=summarize_threshold,
        max_skills=max_skills if enable_skills else 0,
        feedback_handler=feedback_handler,
        fallback_pattern=fallback,
        interrupt_before=[p.strip() for p in interrupt_before.split(",")] if interrupt_before else None,
        interrupt_after=[p.strip() for p in interrupt_after.split(",")] if interrupt_after else None,
        query_cache=query_cache,
        frozen=frozen,
        frozen_template=frozen_template,
    )

    if prompt:
        agent = create_agent(**agent_config)
        result = await agent.ainvoke(prompt)
        console.print(result.output)
    else:
        console.print("[success]agloom shell[/success] — type 'exit' to quit")
        console.print(f"Model: [info]{model or cfg.get('model', 'auto')}[/info]")
        console.print(f"Tools: [info]{len(tools)}[/info]")
        if enable_memory:
            console.print("[info]Memory: enabled[/info]")
        if enable_skills:
            console.print(f"[info]Skills: enabled (max: {max_skills})[/info]")
        console.print()
        await run_shell(create_agent(**agent_config))


if __name__ == "__main__":
    app()
