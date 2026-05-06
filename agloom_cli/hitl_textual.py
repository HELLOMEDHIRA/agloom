"""Textual modal HITL prompts for the TUI.

Installed as the active provider in :class:`agloom_cli.repl_tui.AgloomShellApp`'s
``on_mount`` so HITL gates (tool approval, react ``tool_use_failed`` retry,
clarification answers, …) render as a modal screen instead of trying to share
stdin with the running app.

Triple gates use the structured :class:`~agloom_cli.hitl_ask_types.AskUserRequest`
protocol (:class:`AskUserScreen`). Free-text clarifications use :class:`HITLTextScreen`.

Restored to defaults (Rich) on app exit by :func:`agloom_cli.hitl.reset_ui_providers`.
"""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from agloom.logging_utils import get_logger

from .hitl_ask_types import AskUserRequest, AskUserWidgetResult

_logger = get_logger("agloom_cli.hitl_textual")


def _normalize_ask_user_dismiss(raw: object) -> AskUserWidgetResult:
    """``push_screen`` / ``push_screen_wait`` must yield ``AskUserWidgetResult``; coerce edge returns."""
    if not isinstance(raw, dict):
        _logger.warning("hitl_ask_user_dismiss_not_dict", got_type=type(raw).__name__)
        return {"type": "cancelled"}
    if raw.get("type") == "cancelled":
        return {"type": "cancelled"}
    if raw.get("type") != "answered":
        _logger.warning("hitl_ask_user_unexpected_type", got_type=raw.get("type"))
        return {"type": "cancelled"}
    answers = raw.get("answers")
    if not isinstance(answers, list) or not answers:
        return {"type": "cancelled"}
    return {"type": "answered", "answers": [str(x) for x in answers if x is not None]}


class AskUserScreen(ModalScreen[AskUserWidgetResult]):
    """Modal for :class:`~agloom_cli.hitl_ask_types.AskUserRequest` (HITL multiple-choice / text)."""

    DEFAULT_CSS = """
    AskUserScreen {
        align: center middle;
    }
    AskUserScreen > Vertical {
        width: 76%;
        max-width: 100;
        height: auto;
        padding: 1 2;
        background: $panel;
        border: tall $warning;
    }
    AskUserScreen .hitl_tid {
        color: $text-muted;
        margin-bottom: 1;
    }
    AskUserScreen .hitl_q_text {
        margin-bottom: 1;
    }
    AskUserScreen Button {
        width: 100%;
        margin-top: 0;
    }
    AskUserScreen Input {
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("1", "pick_binding_1", "1", show=False),
        Binding("2", "pick_binding_2", "2", show=False),
        Binding("3", "pick_binding_3", "3", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, request: AskUserRequest) -> None:
        super().__init__()
        self._req = request

    def compose(self):  # type: ignore[override]
        tid = self._req.get("tool_call_id") or ""
        tid_disp = f"{tid[:16]}…" if len(tid) > 16 else tid
        qs = self._req.get("questions") or []
        with Vertical():
            yield Static(f"tool_call_id  {tid_disp}", classes="hitl_tid")
            if not qs:
                yield Static("No questions in request.", classes="hitl_q_text")
                yield Button("Close", id="btn_err_close", variant="primary")
                return
            q0 = qs[0]
            yield Static(q0.get("question") or "", classes="hitl_q_text")
            qtype = q0.get("type") or "text"
            if qtype == "multiple_choice":
                for i, ch in enumerate(q0.get("choices") or [], 1):
                    lab = ch.get("label") or ch.get("value") or str(i)
                    yield Button(f"{i} — {lab}", id=f"btn_{i}", variant="primary")
            else:
                yield Input(placeholder="Answer…", id="hitl_free_text")
                yield Button("Submit", id="btn_txt_go", variant="success")

    def on_mount(self) -> None:  # type: ignore[override]
        qs = self._req.get("questions") or []
        if not qs:
            try:
                self.query_one("#btn_err_close", Button).focus()
            except Exception:
                pass
            return
        q0 = qs[0]
        if (q0.get("type") or "text") == "text":
            try:
                self.query_one("#hitl_free_text", Input).focus()
            except Exception:
                pass
            return
        raw_focus = self._req.get("focus_choice_index")
        focus_i = 2 if raw_focus is None else int(raw_focus)
        focus_i = max(1, min(focus_i, len(q0.get("choices") or [])))
        try:
            self.query_one(f"#btn_{focus_i}", Button).focus()
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss({"type": "cancelled"})

    def action_pick_binding_1(self) -> None:
        self.action_pick_n(1)

    def action_pick_binding_2(self) -> None:
        self.action_pick_n(2)

    def action_pick_binding_3(self) -> None:
        self.action_pick_n(3)

    def action_pick_n(self, n: int) -> None:
        q0 = (self._req.get("questions") or [{}])[0]
        if (q0.get("type") or "text") != "multiple_choice":
            return
        chs = q0.get("choices") or []
        if 1 <= n <= len(chs):
            val = (chs[n - 1].get("value") or "").strip().lower()
            self.dismiss({"type": "answered", "answers": [val]})

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "btn_err_close":
            self.dismiss({"type": "cancelled"})
            return
        if bid == "btn_txt_go":
            try:
                raw = self.query_one("#hitl_free_text", Input).value
            except Exception:
                raw = ""
            self.dismiss({"type": "answered", "answers": [raw]})
            return
        if bid.startswith("btn_"):
            try:
                n = int(bid.replace("btn_", ""))
            except ValueError:
                return
            self.action_pick_n(n)


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
    so the agent's ``user_callback`` dispatches structured :class:`AskUserRequest`
    prompts as modal screens.
    """
    from .hitl import set_ui_providers

    async def _ask_user(req: AskUserRequest) -> AskUserWidgetResult:
        screen = AskUserScreen(req)
        push_wait = getattr(app, "push_screen_wait", None)
        if callable(push_wait):
            raw = await push_wait(screen)
        else:
            raw = await app.push_screen(screen, wait_for_dismiss=True)
        return _normalize_ask_user_dismiss(raw)

    async def _text(*, prompt: str, default: str = "") -> str:
        scr = HITLTextScreen(prompt, default)
        push_wait = getattr(app, "push_screen_wait", None)
        if callable(push_wait):
            raw = await push_wait(scr)
        else:
            raw = await app.push_screen(scr, wait_for_dismiss=True)
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict) and "answers" in raw:
            ans = raw.get("answers")
            if isinstance(ans, list) and ans:
                return str(ans[0])
        return default

    set_ui_providers(ask_user=_ask_user, text_input=_text)
