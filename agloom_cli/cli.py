"""CLI entry point — shell mode by default like opencode/claude code."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.theme import Theme

from .config import (
    ensure_config_ready,
    get_system_prompt,
    get_thread_id,
    load_config,
    resolve_model,
    start_new_session,
)
from .project import detect_project, get_git_info
from .project_rules import load_project_rules
from .repl import run_shell
from .session_manager import (
    SessionManager,
    get_session_context_summary,
    list_all_projects,
    switch_session_by_id,
    update_session_file_summaries,
)
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


@app.command()
def main(
    model: str | None = typer.Option("auto", "--model", "-m", help="Model ID"),
    name: str | None = typer.Option(None, "--name", help="Agent name"),
    system_prompt: str | None = typer.Option(None, "--system-prompt", help="System prompt"),
    tools_dir: Path | None = typer.Option(None, "--tools", "-t", help="Tools directory"),
    enable_memory: bool = typer.Option(True, "--memory/--no-memory", help="Enable memory"),
    memory_path: Path | None = typer.Option(None, "--memory-path", help="Memory storage path"),
    enable_skills: bool = typer.Option(True, "--skills/--no-skills", help="Enable skills"),
    max_skills: int = typer.Option(30, "--max-skills", help="Max skills"),
    session_max_turns: int = typer.Option(20, "--max-turns", help="Max session turns"),
    auto_summarize: bool = typer.Option(True, "--auto-summarize/--no-summarize", help="Auto-summarize"),
    summarize_threshold: int = typer.Option(200000, "--summarize-threshold", help="Summarize threshold"),
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
    max_concurrent: int = typer.Option(4, "--max-concurrent", help="Max concurrent workers"),
    max_retries: int = typer.Option(2, "--max-retries", help="Max retries"),
    retry_delay: float = typer.Option(1.0, "--retry-delay", help="Retry delay"),
    llm_timeout: float = typer.Option(120.0, "--llm-timeout", help="LLM timeout"),
    classifier_timeout: float = typer.Option(30.0, "--classifier-timeout", help="Classifier timeout"),
    fallback_pattern: str | None = typer.Option(None, "--fallback-pattern", help="Fallback pattern"),
    frozen: bool = typer.Option(False, "--frozen", help="Enable frozen mode"),
    frozen_template: str | None = typer.Option(None, "--frozen-template", help="Frozen template"),
    feedback_webhook: str | None = typer.Option(None, "--feedback-webhook", help="Feedback webhook"),
    cache_dir: Path | None = typer.Option(None, "--cache-dir", help="Cache directory"),
    config: Path | None = typer.Option(None, "--config", "-c", help="Config file"),
    session: str | None = typer.Option(None, "--session", "-s", help="Session ID to use"),
    project: Path | None = typer.Option(None, "--project", "-p", help="Project directory (auto-detect context)"),
    rules_dir: Path | None = typer.Option(None, "--rules-dir", help="Custom rules directory (YAML files)"),
    refresh_rules: bool = typer.Option(False, "--refresh-rules", help="Force refresh project rules"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose"),
    no_builtins: bool = typer.Option(False, "--no-builtins", help="Disable built-in tools"),
    version: bool = typer.Option(False, "--version", help="Show version", callback=_version_callback),
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
    enable_memory: bool,
    memory_path: Path | None,
    enable_skills: bool,
    max_skills: int,
    session_max_turns: int,
    auto_summarize: bool,
    summarize_threshold: int,
    mcp_servers: str | None,
    interrupt_before: str | None,
    interrupt_after: str | None,
    interrupt_before_tools: str | None,
    require_approval: bool,
    auto_approve_tools: str | None,
    max_concurrent: int,
    max_retries: int,
    retry_delay: float,
    llm_timeout: float,
    classifier_timeout: float,
    fallback_pattern: str | None,
    frozen: bool,
    frozen_template: str | None,
    feedback_webhook: str | None,
    cache_dir: Path | None,
    config: Path | None,
    session: str | None,
    verbose: bool,
    no_builtins: bool,
    project: Path | None,
    rules_dir: Path | None,
    refresh_rules: bool,
    prompt: str | None,
) -> None:
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.store.memory import InMemoryStore

    from agloom import LongTermStore, SessionMemory, create_agent
    from agloom.feedback.user_feedback import WebhookFeedbackHandler
    from agloom.mcp_support import MCPServerConfig
    from agloom.models import PatternType

    # Ensure config is ready (auto-create if needed)
    ensure_config_ready()

    cfg = load_config(config) if config else load_config(None)

    # Detect project context (use --project flag or auto-detect from cwd)
    project_ctx = detect_project(project)

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
    llm = resolve_model(model or config_model)
    if llm is None:
        console.print("[error]No model configured. Set GROQ_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY.[/error]")
        raise typer.Exit(1)

    # Get or create session (--session flag overrides config/auto-generated ID)
    thread_id = session or get_thread_id(cfg)
    start_new_session(thread_id)

    tools = []
    if not no_builtins:
        tools.extend(_get_builtin_tools())
    if tools_dir or cfg.get("tools", {}).get("dir"):
        tools.extend(discover_tools(tools_dir or cfg.get("tools", {}).get("dir")))

    # MCP servers
    mcp_config = cfg.get("mcp", {})
    mcp_servers_list = mcp_servers or mcp_config.get("servers", "")
    mcp_configs = (
        [MCPServerConfig(name=s.strip(), transport="stdio", command=s.strip()) for s in mcp_servers_list.split(",")]
        if mcp_servers_list
        else []
    )

    # Agent identity
    agent_name = name or ai_config.get("name", "agloom")
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
    enable_memory = memory_config.get("enabled", True) if enable_memory else enable_memory
    session_max_turns = memory_config.get("max_turns", 50) if session_max_turns != 20 else session_max_turns
    auto_summarize = auto_summarize if auto_summarize else cfg.get("auto_summarize", True)
    summarize_threshold = (
        summarize_threshold if summarize_threshold != 200000 else cfg.get("summarize_threshold", 200000)
    )

    # Skills configuration
    skills_config = cfg.get("skills", {})
    enable_skills = enable_skills if not enable_skills else skills_config.get("enabled", True)
    max_skills = max_skills if max_skills != 30 else skills_config.get("max_skills", 30)

    # Execution configuration
    execution_config = cfg.get("execution", {})
    max_concurrent = max_concurrent if max_concurrent != 4 else execution_config.get("max_concurrent", 4)
    max_retries = max_retries if max_retries != 2 else execution_config.get("max_retries", 2)
    retry_delay = retry_delay if retry_delay != 1.0 else execution_config.get("retry_delay", 1.0)
    llm_timeout = llm_timeout if llm_timeout != 120.0 else execution_config.get("llm_timeout", 120.0)
    classifier_timeout = (
        classifier_timeout if classifier_timeout != 30.0 else execution_config.get("classifier_timeout", 30.0)
    )

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

    memory = store = checkpointer = feedback_handler = query_cache = None

    if enable_memory:
        store = LongTermStore(InMemoryStore())
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
            console.print("[warning]Cache requires langchain-huggingface: pip install agloom[huggingface][/warning]")
        except Exception as e:
            console.print(f"[warning]Cache error: {e}")

    fallback = PatternType(fallback_pattern.upper()) if fallback_pattern else None

    agent_config = {
        "model": llm,
        "name": agent_name,
        "tools": tools,
        "system_prompt": agent_system_prompt,
        "memory": memory,
        "store": store,
        "checkpointer": checkpointer,
        "mcp_servers": mcp_configs if mcp_configs else None,
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
    }

    if prompt:
        agent = create_agent(**agent_config)
        result = await agent.ainvoke(prompt)
        console.print(result.output)
    else:
        git_info = get_git_info(project_ctx.root)

        console.print("[success]agloom shell[/success] — type 'exit' to quit")
        console.print(f"Model: [info]{model or config_model}[/info]")
        console.print(f"Tools: [info]{len(tools)}[/info]")
        if enable_memory:
            console.print("[info]Memory: enabled[/info]")
        if enable_skills:
            console.print(f"[info]Skills: enabled (max: {max_skills})[/info]")

        # Show project context
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
        await run_shell(create_agent(**agent_config))


@app.command("sessions")
def list_sessions_cmd() -> None:
    """List all sessions."""

    manager = SessionManager()
    sessions = manager.list_sessions()

    if not sessions:
        console.print("[warning]No sessions found.[/warning]")
        raise typer.Exit()

    from rich.table import Table

    table = Table(title="Sessions")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Project", style="blue")
    table.add_column("Turns", style="yellow")
    table.add_column("Last Active", style="dim")

    for s in sessions:
        table.add_row(
            s.get("id", ""),
            s.get("name", ""),
            s.get("project_path", ""),
            str(s.get("turns", 0)),
            s.get("last_active", "")[:19],
        )

    console.print(table)


@app.command("session-switch")
def switch_session_cmd(session_id: str) -> None:
    """Switch to a different session."""
    session = switch_session_by_id(session_id)

    if not session:
        console.print(f"[error]Session {session_id} not found.[/error]")
        raise typer.Exit(1)

    console.print(f"[success]Switched to session:[/success] {session.get('name')}")
    console.print(f"[dim]Project:[/dim] {session.get('project_path', 'unknown')}")


@app.command("projects")
def list_projects_cmd() -> None:
    """List all projects across sessions."""
    projects = list_all_projects()

    if not projects:
        console.print("[warning]No projects found.[/warning]")
        raise typer.Exit()

    from rich.table import Table

    table = Table(title="Projects")
    table.add_column("Path", style="cyan")
    table.add_column("Session", style="green")
    table.add_column("Turns", style="yellow")
    table.add_column("Last Active", style="dim")

    for p in projects:
        table.add_row(
            p.get("project_path", ""),
            p.get("session_id", ""),
            str(p.get("turns", 0)),
            p.get("last_active", "")[:19],
        )

    console.print(table)


@app.command("refresh-rules")
def refresh_rules_cmd(project: Path | None = None) -> None:
    """Force refresh project rules."""
    from .project_rules import load_project_rules

    proj = project or Path.cwd()
    rules = load_project_rules(proj, force_refresh=True)

    console.print(f"[success]Rules refreshed for:[/success] {proj}")
    console.print(f"[dim]Source:[/dim] {rules.source_file}")
    console.print(f"[dim]Framework:[/dim] {rules.analysis.get('framework', 'unknown')}")
    console.print(f"[dim]Test:[/dim] {rules.analysis.get('test_framework', 'unknown')}")


if __name__ == "__main__":
    app()
