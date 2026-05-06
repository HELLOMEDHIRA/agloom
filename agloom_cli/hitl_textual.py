"""Textual modal HITL prompts for the TUI.

Installed as the active provider in :class:`agloom_cli.repl_tui.AgloomShellApp`'s
``on_mount`` so HITL gates (tool approval, react ``tool_use_failed`` retry,
clarification answers, …) render as a modal screen instead of trying to share
stdin with the running app.

Restored to defaults (Rich) on app exit by :func:`agloom_cli.hitl.reset_ui_providers`.
"""

from __future__ import annotations

from typing import Any

from textual.app import App
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


class HITLChoiceScreen(ModalScreen[str]):
    """Modal tri-state HITL prompt — returns ``accept``/``reject``/``allowlist``."""

    DEFAULT_CSS = """
    HITLChoiceScreen {
        align: center middle;
    }
    HITLChoiceScreen > Vertical {
        width: 70%;
        max-width: 96;
        height: auto;
        padding: 1 2;
        background: $panel;
        border: tall $warning;
    }
    HITLChoiceScreen .hitl_title {
        color: $warning;
        text-style: bold;
        margin-bottom: 1;
    }
    HITLChoiceScreen .hitl_detail {
        margin-bottom: 1;
    }
    HITLChoiceScreen .hitl_footer {
        color: $text-muted;
        margin-bottom: 1;
    }
    HITLChoiceScreen Button {
        width: 100%;
        margin-top: 0;
    }
    """

    BINDINGS = [
        Binding("1,a", "pick('accept')", "Accept", show=False),
        Binding("2,r,escape", "pick('reject')", "Reject", show=False),
        Binding("3,l", "pick('allowlist')", "Always allow", show=False),
    ]

    def __init__(
        self,
        *,
        title: str,
        subtitle: str,
        detail: str,
        footer: str | None,
        row1: str,
        row2: str,
        row3: str,
        default: str = "2",
    ) -> None:
        super().__init__()
        self._title = title
        self._subtitle = subtitle
        self._detail = detail
        self._footer = footer
        self._row1 = row1
        self._row2 = row2
        self._row3 = row3
        self._default = default

    def compose(self):  # type: ignore[override]
        with Vertical():
            yield Static(f"{self._title}\n[dim]{self._subtitle}[/dim]", classes="hitl_title")
            yield Static(self._detail, classes="hitl_detail")
            if self._footer:
                yield Static(self._footer, classes="hitl_footer")
            yield Button(f"1 — {self._row1}", id="btn_accept", variant="success")
            yield Button(f"2 — {self._row2}", id="btn_reject", variant="error")
            yield Button(f"3 — {self._row3}", id="btn_allowlist", variant="primary")

    def on_mount(self) -> None:  # type: ignore[override]
        target = {"1": "btn_accept", "2": "btn_reject", "3": "btn_allowlist"}.get(self._default, "btn_reject")
        try:
            self.query_one(f"#{target}", Button).focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {"btn_accept": "accept", "btn_reject": "reject", "btn_allowlist": "allowlist"}
        self.dismiss(mapping.get(event.button.id or "", "reject"))

    def action_pick(self, choice: str) -> None:
        self.dismiss(choice)


class HITLTextScreen(ModalScreen[str]):
    """Modal free-text HITL prompt — used for clarification answers."""

    DEFAULT_CSS = """
    HITLTextScreen {
        align: center middle;
    }
    HITLTextScreen > Vertical {
        width: 70%;
        max-width: 96;
        height: auto;
        padding: 1 2;
        background: $panel;
        border: tall $primary;
    }
    HITLTextScreen .hitl_question {
        text-style: bold;
        margin-bottom: 1;
    }
    HITLTextScreen Input {
        margin-bottom: 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, prompt: str, default: str = "") -> None:
        super().__init__()
        self._prompt_text = prompt
        self._default = default

    def compose(self):  # type: ignore[override]
        with Vertical():
            yield Static(self._prompt_text, classes="hitl_question")
            yield Input(value=self._default, placeholder="Type answer and press Enter…", id="hitl_answer")
            yield Button("Submit", id="btn_submit", variant="primary")

    def on_mount(self) -> None:  # type: ignore[override]
        try:
            self.query_one("#hitl_answer", Input).focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value or self._default)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_submit":
            try:
                value = self.query_one("#hitl_answer", Input).value
            except Exception:
                value = ""
            self.dismiss(value or self._default)

    def action_cancel(self) -> None:
        self.dismiss(self._default)


def install_textual_providers(app: App) -> None:
    """Wire ``app`` as the active HITL prompt UI.

    Call from the TUI app's ``on_mount``. The providers capture ``app`` by closure
    so the agent's ``user_callback`` (constructed earlier with the Rich provider)
    transparently dispatches every prompt as a modal screen instead.
    """
    from .hitl import set_ui_providers

    async def _triple(**kwargs: Any) -> str:
        return await app.push_screen_wait(HITLChoiceScreen(**kwargs))

    async def _text(*, prompt: str, default: str = "") -> str:
        return await app.push_screen_wait(HITLTextScreen(prompt, default))

    set_ui_providers(triple_choice=_triple, text_input=_text)
