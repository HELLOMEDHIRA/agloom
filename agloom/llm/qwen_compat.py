"""Qwen3 / vLLM / LiteLLM chat-template compatibility helpers for tool-bearing agents."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ..logging_utils import get_logger
from ..multimodal import content_blocks_to_text

logger = get_logger(__name__)

_DEFAULT_USER_TURN = "Use the available tools to complete the requested task."

_QWEN_MODEL_MARKERS = (
    "qwen",
    "qwq",
)

# Vendors where ``tool_choice=required`` on the opening turn is known-safe.
_KNOWN_STRICT_TOOL_CHOICE_VENDORS = (
    "groq",
    "cerebras",
)


class _ChatTemplateCompatProxy:
    """Wrap any chat model / RunnableBinding — repair messages on every LLM call."""

    def __init__(self, inner: Any, model_label: str) -> None:
        object.__setattr__(self, "_agloom_inner", inner)
        object.__setattr__(self, "_agloom_label", model_label)

    def __repr__(self) -> str:
        inner = object.__getattribute__(self, "_agloom_inner")
        return f"ChatTemplateCompatProxy({inner!r})"

    def __getattr__(self, name: str) -> Any:
        inner = object.__getattribute__(self, "_agloom_inner")
        return getattr(inner, name)

    def _label(self) -> str:
        return object.__getattribute__(self, "_agloom_label")

    def _wrap_child(self, child: Any) -> Any:
        inner = object.__getattribute__(self, "_agloom_inner")
        if child is inner:
            return self
        return _ChatTemplateCompatProxy(child, self._label())

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        inner = object.__getattribute__(self, "_agloom_inner")
        return self._wrap_child(
            inner.bind_tools(tools, **_sanitize_bind_kwargs(kwargs, self._label()))
        )

    def bind(self, **kwargs: Any) -> Any:
        inner = object.__getattribute__(self, "_agloom_inner")
        return self._wrap_child(inner.bind(**_sanitize_bind_kwargs(kwargs, self._label())))

    def with_config(self, config: Any) -> Any:
        inner = object.__getattribute__(self, "_agloom_inner")
        return self._wrap_child(inner.with_config(config))

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        inner = object.__getattribute__(self, "_agloom_inner")
        return inner.invoke(
            _coerce_llm_input(input, self._label()),
            config,
            **_sanitize_invoke_kwargs(kwargs, self._label()),
        )

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        inner = object.__getattribute__(self, "_agloom_inner")
        return await inner.ainvoke(
            _coerce_llm_input(input, self._label()),
            config,
            **_sanitize_invoke_kwargs(kwargs, self._label()),
        )

    def stream(self, input: Any, config: Any = None, **kwargs: Any) -> Iterator[Any]:
        inner = object.__getattribute__(self, "_agloom_inner")
        return inner.stream(
            _coerce_llm_input(input, self._label()),
            config,
            **_sanitize_invoke_kwargs(kwargs, self._label()),
        )

    async def astream(self, input: Any, config: Any = None, **kwargs: Any) -> AsyncIterator[Any]:
        inner = object.__getattribute__(self, "_agloom_inner")
        async for chunk in inner.astream(
            _coerce_llm_input(input, self._label()),
            config,
            **_sanitize_invoke_kwargs(kwargs, self._label()),
        ):
            yield chunk

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Any:
        inner = object.__getattribute__(self, "_agloom_inner")
        return inner._generate(
            _coerce_llm_input(messages, self._label()),
            stop,
            run_manager,
            **_sanitize_invoke_kwargs(kwargs, self._label()),
        )

    async def _agenerate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Any:
        inner = object.__getattribute__(self, "_agloom_inner")
        return await inner._agenerate(
            _coerce_llm_input(messages, self._label()),
            stop,
            run_manager,
            **_sanitize_invoke_kwargs(kwargs, self._label()),
        )


def wrap_chat_model_for_react_compat(llm: Any, model_spec: Any) -> Any:
    """Wrap the resolved LLM so every invoke/stream path repairs messages (not only middleware)."""
    if isinstance(model_spec, str):
        label = model_spec.strip()
    else:
        from .model_resolver import describe_llm

        _slug, label = describe_llm(llm)
    label = label or extract_model_label(llm)
    tag_llm_for_chat_template_compat(llm, label)
    if isinstance(llm, _ChatTemplateCompatProxy):
        return llm
    return _ChatTemplateCompatProxy(llm, label)


def tag_llm_for_chat_template_compat(llm: Any, model_spec: Any) -> None:
    """Stamp the resolved model string on the LLM for middleware (LiteLLM model groups)."""
    if isinstance(model_spec, str):
        label = model_spec.strip()
    else:
        from .model_resolver import describe_llm

        _slug, label = describe_llm(llm)
    if not label:
        return
    for target in _unwrap_model_chain(llm):
        try:
            setattr(target, "_agloom_model_label", label)
        except Exception:
            pass


def _unwrap_model_chain(model: Any, *, max_depth: int = 12) -> list[Any]:
    seen: set[int] = set()
    chain: list[Any] = []
    current: Any = model
    for _ in range(max_depth):
        if current is None:
            break
        oid = id(current)
        if oid in seen:
            break
        seen.add(oid)
        chain.append(current)
        nxt = getattr(current, "bound", None) or getattr(current, "runnable", None)
        if nxt is None or nxt is current:
            break
        current = nxt
    return chain


def extract_model_label(model: Any) -> str:
    """Best-effort model id from a LangChain chat model (incl. RunnableBinding wrappers)."""
    hints: list[str] = []
    for node in _unwrap_model_chain(model):
        tagged = getattr(node, "_agloom_model_label", None)
        if tagged:
            hints.append(str(tagged))
        for attr in (
            "model_name",
            "model",
            "model_id",
            "model_group",
            "deployment_name",
        ):
            value = getattr(node, attr, None)
            if value:
                hints.append(str(value))
        cls = type(node).__name__.lower()
        if "litellm" in cls:
            hints.append("litellm")
        if "vllm" in cls:
            hints.append("vllm")
        kwargs = getattr(node, "kwargs", None)
        if isinstance(kwargs, dict):
            for key in ("model", "model_name", "model_group"):
                v = kwargs.get(key)
                if v:
                    hints.append(str(v))
    return " ".join(hints).lower()


def model_needs_qwen_chat_template_compat(model_label: str) -> bool:
    """True when the provider chat template is strict (Qwen3, vLLM, opaque LiteLLM groups)."""
    label = (model_label or "").lower()
    if any(marker in label for marker in _QWEN_MODEL_MARKERS):
        return True
    if "vllm" in label or "chatlitellm" in label:
        return True
    # LiteLLM router aliases (e.g. model group ``qwen36fp8``) often omit ``qwen`` in the client id.
    if "litellm" in label and not any(v in label for v in _KNOWN_STRICT_TOOL_CHOICE_VENDORS):
        return True
    return False


def _human_content_as_text(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        text = content.strip()
        return text or None
    if isinstance(content, list):
        text = content_blocks_to_text(content).strip()
        return text or None
    text = str(content).strip()
    return text or None


def _replace_human_content(msg: Any, text: str) -> Any:
    if isinstance(msg, HumanMessage):
        return HumanMessage(content=text, id=msg.id, name=msg.name)
    if isinstance(msg, dict):
        updated = dict(msg)
        updated["content"] = text
        return updated
    content = text
    try:
        return msg.model_copy(update={"content": content})  # type: ignore[attr-defined]
    except Exception:
        try:
            msg.content = content  # type: ignore[attr-defined]
        except Exception:
            pass
    return msg


def _is_human_message(msg: Any) -> bool:
    if isinstance(msg, HumanMessage):
        return True
    if isinstance(msg, dict):
        role = str(msg.get("role") or "").lower()
        return role in ("user", "human")
    role = str(getattr(msg, "type", None) or getattr(msg, "role", None) or "").lower()
    return role in ("human", "user")


def _has_nonempty_user_text(messages: list[Any]) -> bool:
    for msg in messages:
        if not _is_human_message(msg):
            continue
        if isinstance(msg, HumanMessage):
            raw = msg.content
        elif isinstance(msg, dict):
            raw = msg.get("content")
        else:
            raw = getattr(msg, "content", None)
        if _human_content_as_text(raw):
            return True
    return False


def _latest_user_text_from_messages(messages: list[Any]) -> str | None:
    for msg in reversed(messages):
        if not _is_human_message(msg):
            continue
        if isinstance(msg, HumanMessage):
            raw = msg.content
        elif isinstance(msg, dict):
            raw = msg.get("content")
        else:
            raw = getattr(msg, "content", None)
        text = _human_content_as_text(raw)
        if text:
            return text
    return None


def normalize_messages_for_chat_template(messages: list[Any]) -> list[Any]:
    """Flatten multimodal user content blocks to plain strings."""
    if not messages:
        return messages
    out: list[Any] = []
    changed = False
    for msg in messages:
        if not _is_human_message(msg):
            out.append(msg)
            continue
        if isinstance(msg, HumanMessage):
            raw = msg.content
        elif isinstance(msg, dict):
            raw = msg.get("content")
        else:
            raw = getattr(msg, "content", None)
        if isinstance(raw, str) and raw.strip():
            out.append(msg)
            continue
        flat = _human_content_as_text(raw)
        if flat is None:
            out.append(msg)
            continue
        out.append(_replace_human_content(msg, flat))
        changed = True
    return out if changed else messages


def _is_system_message(msg: Any) -> bool:
    if isinstance(msg, SystemMessage):
        return True
    if isinstance(msg, dict):
        return str(msg.get("role") or "").lower() == "system"
    role = str(getattr(msg, "type", None) or getattr(msg, "role", None) or "").lower()
    return role == "system"


def _sanitize_bind_kwargs(kwargs: dict[str, Any], model_label: str) -> dict[str, Any]:
    if not model_needs_qwen_chat_template_compat(model_label):
        return kwargs
    out = dict(kwargs)
    out.pop("tool_choice", None)
    return out


def _sanitize_invoke_kwargs(kwargs: dict[str, Any], model_label: str) -> dict[str, Any]:
    if not model_needs_qwen_chat_template_compat(model_label):
        return kwargs
    out = dict(kwargs)
    out.pop("tool_choice", None)
    return out


def _coerce_llm_input(input: Any, model_label: str) -> Any:
    if isinstance(input, list):
        return ensure_messages_for_chat_template(input)
    if isinstance(input, dict) and "messages" in input:
        patched = dict(input)
        patched["messages"] = ensure_messages_for_chat_template(list(input["messages"] or []))
        return patched
    return input


def ensure_messages_for_chat_template(
    messages: list[Any],
    *,
    state: dict[str, Any] | None = None,
) -> list[Any]:
    """Flatten user blocks, fill empty user turns, guarantee a non-empty user query."""
    repaired = repair_messages_for_chat_template(messages, state=state)
    if _has_nonempty_user_text(repaired):
        return repaired

    for idx, msg in enumerate(repaired):
        if not _is_human_message(msg):
            continue
        if isinstance(msg, HumanMessage):
            raw = msg.content
        elif isinstance(msg, dict):
            raw = msg.get("content")
        else:
            raw = getattr(msg, "content", None)
        if not _human_content_as_text(raw):
            logger.warning(
                f"[qwen_compat] Empty user message at index {idx} — filling default user turn"
            )
            repaired[idx] = _replace_human_content(msg, _DEFAULT_USER_TURN)
            return repaired

    insert_at = 0
    for idx, msg in enumerate(repaired):
        if _is_system_message(msg):
            insert_at = idx + 1
        else:
            break
    logger.warning(
        f"[qwen_compat] No user query in {len(repaired)} message(s) — inserting default user turn"
    )
    return repaired[:insert_at] + [HumanMessage(content=_DEFAULT_USER_TURN)] + repaired[insert_at:]


def repair_messages_for_chat_template(
    messages: list[Any],
    *,
    state: dict[str, Any] | None = None,
) -> list[Any]:
    """Normalize user blocks and ensure a non-empty user query exists for strict templates."""
    repaired = normalize_messages_for_chat_template(list(messages or []))
    if _has_nonempty_user_text(repaired):
        return repaired

    state_msgs = list((state or {}).get("messages") or [])
    fallback = _latest_user_text_from_messages(state_msgs) or _DEFAULT_USER_TURN
    if repaired and _is_human_message(repaired[-1]):
        return repaired[:-1] + [_replace_human_content(repaired[-1], fallback)]
    return [HumanMessage(content=fallback), *repaired]


def qwen_model_settings_patch(existing: dict[str, Any] | None) -> dict[str, Any]:
    """Disable Qwen thinking in tool loops when the upstream supports chat_template_kwargs."""
    settings = dict(existing or {})
    extra = dict(settings.get("extra_body") or {})
    ctk = dict(extra.get("chat_template_kwargs") or {})
    ctk.setdefault("enable_thinking", False)
    extra["chat_template_kwargs"] = ctk
    settings["extra_body"] = extra
    return settings


def resolve_react_tool_choice(
    messages: list[Any] | None,
    *,
    model_label: str,
) -> str | None:
    """Opening-turn tool choice for ReAct; strict templates must not use ``required``."""
    if not messages:
        return None
    if model_needs_qwen_chat_template_compat(model_label):
        return None
    opening = len(messages) == 1 and _is_human_message(messages[0])
    if opening:
        return "required"
    return None
