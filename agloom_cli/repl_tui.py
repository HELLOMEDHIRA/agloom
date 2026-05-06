"""Textual-based interactive shell: scrollable chat (left) + fixed session card (right).

Uses the alternate screen so the session sidebar stays visible while the transcript scrolls.
Non-TTY runs (CI, piped IO) automatically fall back to :func:`agloom_cli.repl.run_shell_plain`.
"""

from __future__ import annotations

import os
import traceback
from typing import Any

from rich.text import Text

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.theme import Theme
from textual.widgets import Footer, Input, RichLog, Static

from .config import add_to_session_history
from .repl import (
    ShellState,
    _append_trace_line,
    _live_agent_panel,
    _session_side_card,
    _thinking_footer_panel,
    _SESSION_CARD_MAX_W,
    _SESSION_CARD_MIN_W,
    reset_ui,
    tui_soft_answer,
    tui_soft_done_banner,
    tui_soft_help_panel,
    tui_soft_status_banner,
    tui_soft_user_message,
    tui_soft_warn_banner,
)
from .session_resume import (
    hydrate_repl_history_from_agent_memory,
    hydrate_repl_history_from_session_json,
)

# Frosted / glass-inspired palette (soft contrast; works on integrated terminals).
AGLOOM_GLASS_THEME = Theme(
    name="agloom-glass",
    primary="#8ab4d8",
    secondary="#6d8aa8",
    accent="#b9a8d9",
    warning="#d4b87a",
    error="#c89090",
    success="#8fc9a3",
    foreground="#c5ced9",
    background="#0c1016",
    surface="#121a24",
    panel="#18222c",
    dark=True,
    luminosity_spread=0.1,
    text_alpha=0.93,
    variables={
        "footer-key-foreground": "#8ab4d8",
        "input-selection-background": "#6d8aa8 28%",
        "block-cursor-background": "#8ab4d8",
        "block-cursor-foreground": "#0c1016",
    },
)


class AgloomShellApp(App[None]):
    """Full-screen TUI with a persistent session column."""

    ENABLE_COMMAND_PALETTE = False
    TITLE = "agloom"
    SUB_TITLE = ""
    CSS = """
    Screen {
        layout: vertical;
        background: $background;
    }
    #body {
        layout: horizontal;
        height: 1fr;
        min-height: 0;
        margin: 0 1;
    }
    #main_col {
        layout: vertical;
        width: 1fr;
        min-width: 24;
        min-height: 0;
        padding-right: 1;
    }
    #live_turn {
        max-height: 22;
        min-height: 0;
        margin-bottom: 1;
        padding-left: 1;
        transition: opacity 200ms in_out_cubic;
    }
    #chat {
        height: 1fr;
        min-height: 5;
        padding-left: 1;
        background: $panel 22%;
        scrollbar-color: $primary 18%;
        scrollbar-color-hover: $primary 38%;
        scrollbar-color-active: $primary 48%;
    }
    #sidebar {
        width: 40;
        min-width: 32;
        max-width: 52;
        padding: 0 1;
        background: $surface 70%;
        border-left: outer $primary 16%;
        transition: background 320ms in_out_cubic, border 320ms in_out_cubic;
    }
    #prompt {
        height: auto;
        margin: 1 1 0 1;
        padding: 0 1;
        border: tall $primary 18%;
        background: $panel 28%;
        transition: border 240ms in_out_expo, background 240ms in_out_expo;
    }
    #prompt:focus {
        border: tall $primary 45%;
        background: $panel 45%;
    }
    Footer {
        background: $surface 82%;
        border-top: wide $primary 10%;
        transition: background 260ms in_out_cubic;
    }
    """

    BINDINGS = [
        Binding("ctrl+shift+q", "quit", "Exit", show=True),
        Binding("f10", "quit", show=False),
        Binding("ctrl+q", "quit", show=False),
    ]

    def __init__(
        self,
        agent: Any,
        *,
        welcome: str,
        verbose: bool,
        llm_status: str | None,
        thread_id: str | None,
        tools_count: int | None,
    ) -> None:
        super().__init__()
        self.register_theme(AGLOOM_GLASS_THEME)
        self.agent = agent
        self._welcome = welcome
        self._verbose = verbose
        self._llm_status = llm_status
        self._thread_id_arg = thread_id
        self._tools_count = tools_count
        self.state: ShellState | None = None
        self.invoke_tid: str = ""
        self.status_model: str = "auto:auto"
        self.working_dir: str = ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="main_col"):
                yield Static("", id="live_turn")
                yield RichLog(
                    id="chat",
                    highlight=True,
                    markup=True,
                    wrap=True,
                    max_lines=12_000,
                    auto_scroll=True,
                )
            yield Static("", id="sidebar")
        yield Input(
            id="prompt",
            placeholder="Type a message…  ·  exit  ·  help  ·  ctrl+shift+q or F10 to quit",
        )
        yield Footer()

    async def on_mount(self) -> None:
        self.theme = "agloom-glass"
        reset_ui()
        # HITL prompts must render as Textual modals — stdin is owned by the app,
        # so the default Rich/console provider wouldn't reach the user. Plain shell
        # automatically reverts to the Rich providers on TUI exit (see run_shell_tui).
        try:
            from .hitl_textual import install_textual_providers

            install_textual_providers(self)
        except Exception:
            pass
        self.state = ShellState()
        assert self.state is not None
        self.working_dir = os.getcwd()
        self.state.ui.working_dir = self.working_dir
        self.state.ui.langsmith_enabled = bool(os.environ.get("LANGCHAIN_TRACING_V2"))
        self.invoke_tid = self._thread_id_arg or self.state.ui.thread_id
        self.state.ui.thread_id = self.invoke_tid[:8] if len(self.invoke_tid) > 8 else self.invoke_tid
        self.status_model = self._llm_status or "auto:auto"

        if not await hydrate_repl_history_from_agent_memory(self.agent, self.invoke_tid, self.state):
            hydrate_repl_history_from_session_json(self.invoke_tid, self.state)

        self.sub_title = self.invoke_tid[:8] if len(self.invoke_tid) >= 8 else self.invoke_tid
        self._refresh_sidebar()
        log = self.query_one("#chat", RichLog)
        log.write(tui_soft_status_banner(self._welcome))
        self._replay_history(log)
        self.query_one("#prompt", Input).focus()

    def on_resize(self) -> None:
        if self.state is not None and self.size and self.size.width > 0:
            try:
                self._refresh_sidebar()
            except Exception:
                pass

    def _sidebar_width(self) -> int:
        w = self.size.width if self.size and self.size.width > 0 else 80
        return min(
            _SESSION_CARD_MAX_W,
            max(_SESSION_CARD_MIN_W, min(_SESSION_CARD_MAX_W, w // 3 + 8)),
        )

    def _refresh_sidebar(self) -> None:
        if self.state is None:
            return
        card = _session_side_card(
            session_id_full=self.invoke_tid,
            turns=len(self.state.history),
            tokens_est=self.state.total_tokens_est,
            model=self.status_model,
            tools_count=self._tools_count,
            cwd=self.working_dir,
            langsmith_on=self.state.ui.langsmith_enabled,
            card_width=self._sidebar_width(),
            tui_soft=True,
        )
        self.query_one("#sidebar", Static).update(card)

    def _replay_history(self, log: RichLog) -> None:
        if not self.state:
            return
        for q, a in self.state.history:
            log.write(tui_soft_user_message(q))
            if (a or "").strip():
                log.write(tui_soft_answer(a))

    def _handle_slash_commands(self, text: str) -> bool:
        """Built-in REPL commands; return True if handled."""
        if self.state is None:
            return False
        low = text.strip().lower()
        if low in ("exit", "quit", "q"):
            self.exit()
            return True
        if low == "clear":
            self.query_one("#chat", RichLog).clear()
            self.query_one("#live_turn", Static).update(Text(""))
            return True
        if low == "history":
            log = self.query_one("#chat", RichLog)
            if not self.state.history:
                log.write("[dim]No history yet.[/dim]")
            else:
                for i, (q, a) in enumerate(self.state.history, 1):
                    log.write(f"[dim]{i}.[/dim] [magenta]> {q}[/magenta]")
                    log.write(f"   {a[:120]}…" if len(a) > 120 else f"   {a}")
            return True
        if low == "help":
            self.query_one("#chat", RichLog).write(tui_soft_help_panel())
            return True
        if low in ("thinking", "thinking toggle"):
            self.state.expand_thinking = not self.state.expand_thinking
            mode = "full reasoning" if self.state.expand_thinking else "compact"
            self.query_one("#chat", RichLog).write(f"[dim]Thinking:[/dim] [cyan]{mode}[/cyan]")
            return True
        if low == "thinking on":
            self.state.expand_thinking = True
            self.query_one("#chat", RichLog).write("[dim]Thinking:[/dim] [cyan]full[/cyan]")
            return True
        if low == "thinking off":
            self.state.expand_thinking = False
            self.query_one("#chat", RichLog).write("[dim]Thinking:[/dim] [cyan]compact[/cyan]")
            return True
        return False

    async def action_quit(self) -> None:
        self.exit()

    @on(Input.Submitted, "#prompt")
    async def on_prompt_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text or self.state is None:
            return
        if self._handle_slash_commands(text):
            return
        self.run_worker(self._run_turn(text), exclusive=True)

    async def _run_turn(self, prompt_text: str) -> None:
        assert self.state is not None
        live = self.query_one("#live_turn", Static)
        log = self.query_one("#chat", RichLog)
        inp = self.query_one("#prompt", Input)
        inp.disabled = True
        try:
            log.write(tui_soft_user_message(prompt_text))

            thinking_lines: list[str] = []
            tool_status: dict[str, str] = {}
            stream_text = Text()

            if not hasattr(self.agent, "astream_events"):
                if not hasattr(self.agent, "ainvoke"):
                    raise RuntimeError("Agent supports neither astream_events nor ainvoke")
                log.write(tui_soft_warn_banner("No event stream — using ainvoke."))
                result = await self.agent.ainvoke(prompt_text, thread_id=self.invoke_tid)
                stream_text.append(result.output or "")
            else:
                async for event in self.agent.astream_events(prompt_text, thread_id=self.invoke_tid):
                    event_type = event.type
                    data = event.data
                    if event_type in (
                        "thinking",
                        "llm_call",
                        "worker_start",
                        "worker_end",
                        "cache_hit",
                        "reflection",
                        "fallback",
                    ):
                        _append_trace_line(thinking_lines, event_type, data)
                        live.update(_live_agent_panel(thinking_lines, stream_text, tui_soft=True))
                    elif event_type == "token":
                        content = data.get("content", "")
                        if content:
                            stream_text.append(str(content))
                        live.update(_live_agent_panel(thinking_lines, stream_text, tui_soft=True))
                    elif event_type == "tool_call":
                        tool_name = data.get("name", "unknown")
                        tool_id = data.get("id", "")
                        tool_status[tool_id] = tool_name
                        tin = data.get("input", "")
                        tin_s = str(tin)[:120] + "…" if len(str(tin)) > 120 else str(tin)
                        thinking_lines.append(f"→ [yellow]{tool_name}[/yellow] {tin_s}")
                        live.update(_live_agent_panel(thinking_lines, stream_text, tui_soft=True))
                    elif event_type == "tool_result":
                        tool_id = data.get("id", "")
                        tool_name = tool_status.pop(tool_id, "unknown")
                        res = data.get("output", "")
                        preview = str(res)[:100] + "…" if len(str(res)) > 100 else str(res)
                        thinking_lines.append(f"  [green]✓[/green] {tool_name}: {preview}")
                        live.update(_live_agent_panel(thinking_lines, stream_text, tui_soft=True))
                    elif event_type == "error":
                        error_msg = data.get("error", "Unknown error")
                        thinking_lines.append(f"✗ {error_msg}")
                        live.update(_live_agent_panel(thinking_lines, stream_text, tui_soft=True))
                    elif event_type == "done":
                        result = data.get("result") or {}
                        out = result.get("output", "")
                        if out and not stream_text.plain.strip():
                            stream_text.append(str(out))
                        live.update(_live_agent_panel(thinking_lines, stream_text, tui_soft=True))

            live.update(Text(""))
            full_output = stream_text.plain
            tp = _thinking_footer_panel(
                thinking_lines, expanded=self.state.expand_thinking, tui_soft=True
            )
            if tp is not None:
                log.write(tp)
            if full_output.strip():
                log.write(tui_soft_answer(full_output))

            self.state.add_turn(prompt_text, full_output)
            try:
                add_to_session_history(self.invoke_tid, "user", prompt_text)
                add_to_session_history(self.invoke_tid, "assistant", full_output)
            except Exception:
                pass

            self._refresh_sidebar()
            log.write(tui_soft_done_banner(len(self.state.history)))
        except Exception as e:
            if self._verbose:
                log.write(traceback.format_exc())
            log.write(f"[bold red]✗[/bold red] {e}")
        finally:
            inp.disabled = False
            inp.focus()


async def run_shell_tui(
    agent: Any,
    *,
    welcome: str = "Ready to code!",
    verbose: bool = False,
    llm_status: str | None = None,
    thread_id: str | None = None,
    tools_count: int | None = None,
) -> None:
    app = AgloomShellApp(
        agent,
        welcome=welcome,
        verbose=verbose,
        llm_status=llm_status,
        thread_id=thread_id,
        tools_count=tools_count,
    )
    try:
        await app.run_async()
    finally:
        # Restore Rich-based HITL providers so any post-TUI prompts (or a
        # subsequent plain-shell run in the same process) work normally.
        try:
            from .hitl import reset_ui_providers

            reset_ui_providers()
        except Exception:
            pass
