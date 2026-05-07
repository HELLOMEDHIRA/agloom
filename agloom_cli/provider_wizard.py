"""Interactive LLM provider setup — LangChain chat factories plus Agloom extras."""

from __future__ import annotations

import copy
import importlib.util
import os
import sys
from textwrap import fill
from typing import Any

from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt

from .langchain_index_overview import INIT_CHAT_SLUG_TITLES, NON_CHAT_INDEX_BRANDS
from .model_resolver import augment_patch_api_keys_from_env
from .provider_registry import (
    WIZARD_DEFAULT_MODELS as _DEFAULT_MODEL_BY_SLUG,
)
from .provider_registry import (
    WIZARD_ENV_KEYS as _ENV_KEYS_BY_SLUG,
)
from .provider_registry import (
    wizard_extra_rows,
)

# LangChain’s built-in registry (same providers ``init_chat_model`` supports first-class).
try:
    from langchain.chat_models.base import _BUILTIN_PROVIDERS as _LC_BUILTIN_PROVIDERS
except ImportError:  # pragma: no cover
    _LC_BUILTIN_PROVIDERS = {}

# ``_DEFAULT_MODEL_BY_SLUG`` and ``_ENV_KEYS_BY_SLUG`` are imported from
# :mod:`agloom_cli.provider_registry` (above). To add a provider, edit ``provider_registry.PROVIDERS``.


def _pip_package_for_module(module_path: str) -> str:
    return module_path.split(".", maxsplit=1)[0].replace("_", "-")


def langchain_init_chat_provider_table() -> list[tuple[str, str, str]]:
    """Rows ``(slug, pip_package, chat_class)`` from LangChain’s registry, sorted by slug."""
    rows: list[tuple[str, str, str]] = []
    for slug in sorted(_LC_BUILTIN_PROVIDERS.keys()):
        mod_path, class_name, _creator = _LC_BUILTIN_PROVIDERS[slug]
        rows.append((slug, _pip_package_for_module(mod_path), class_name))
    return rows


def wizard_provider_table() -> list[tuple[str, str, str, str]]:
    """Rows ``(slug, pip_package, class_name, display_title)`` for the interactive wizard.

    Merges LangChain's ``init_chat_model`` registry with extras derived from
    :mod:`agloom_cli.provider_registry` (any provider with a ``chat_class`` + ``pip_extra``
    whose aliases are not already in LangChain's registry). Sorted by display title.
    """
    seen: set[str] = set()
    rows: list[tuple[str, str, str, str]] = []
    for slug, pip_pkg, cls_name in langchain_init_chat_provider_table():
        seen.add(slug)
        title = INIT_CHAT_SLUG_TITLES.get(slug, slug.replace("_", " ").title())
        rows.append((slug, pip_pkg, cls_name, title))
    for slug, pip_pkg, cls_name, title in wizard_extra_rows(seen):
        if slug not in seen:
            rows.append((slug, pip_pkg, cls_name, title))
            seen.add(slug)
    rows.sort(key=lambda r: r[3].lower())
    return rows


def _package_importable(pip_root: str) -> bool:
    py_mod = pip_root.replace("-", "_")
    return importlib.util.find_spec(py_mod) is not None


def _existing_api_keys(ai: dict[str, Any]) -> dict[str, str]:
    raw = ai.get("api_keys")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and v is not None and str(v).strip():
            out[k.strip()] = str(v).strip()
    return out


def _env_keys_for_slug(slug: str) -> list[str]:
    """Wizard env-prompt list for *slug* (table override, then ``<SLUG>_API_KEY`` heuristic)."""
    if slug in _ENV_KEYS_BY_SLUG:
        return list(_ENV_KEYS_BY_SLUG[slug])
    return [f"{slug.upper()}_API_KEY"]


def _default_model(slug: str) -> str:
    return _DEFAULT_MODEL_BY_SLUG.get(slug, "replace-with-your-model-id")


def _interactive_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def run_interactive_provider_wizard(console: Console, base_cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Prompt for provider, model, secrets, optional base URL; return ``ai`` patch or ``None`` if cancelled."""
    if not _interactive_tty():
        return None

    builtin = langchain_init_chat_provider_table()
    if not builtin:
        console.print(
            "[error]Could not load LangChain’s built-in provider registry. "
            "Is ``langchain`` installed?[/error]"
        )
        return None

    table = wizard_provider_table()

    console.print(
        "\n[bold cyan]Chat LLM backends[/bold cyan] "
        "[dim](LangChain ``init_chat_model`` registry + Agloom extras — sorted by name)[/dim]\n"
        "[dim]Full index also lists vector DBs, loaders, and tools: "
        "https://docs.langchain.com/oss/python/integrations/providers/all_providers[/dim]\n"
        "[dim]Install the PyPI package in parentheses when marked ○.[/dim]\n"
    )
    for i, (slug, pip_pkg, cls_name, title) in enumerate(table, start=1):
        ok = "[green]✓[/green]" if _package_importable(pip_pkg) else "[yellow]○[/yellow]"
        console.print(
            f"  {i:2}. {ok} [bold]{title:34}[/bold] [dim]{slug:22}[/dim] [dim]{pip_pkg}[/dim] — {cls_name}"
        )

    width = getattr(console, "width", 88) or 88
    console.print(
        "\n[bold dim]Also on the LangChain index — not this chat menu[/bold dim] "
        "[dim](data stores, search, loaders, …):[/dim]"
    )
    console.print(fill(", ".join(NON_CHAT_INDEX_BRANDS), width=max(60, min(width - 4, 110))))
    console.print(
        "[dim]Wire those from Python when you build agents. Extra model APIs often work via "
        "[cyan]-m litellm:provider/model[/cyan].[/dim]\n"
    )

    choice = IntPrompt.ask(
        "\nSelect provider by number [dim](0 = cancel)[/dim]",
        default=0,
    )
    if choice <= 0 or choice > len(table):
        return None

    slug, pip_pkg, _cls, _title = table[choice - 1]
    if not _package_importable(pip_pkg):
        console.print(
            f"\n[yellow]Package `{pip_pkg}` does not look installed.[/yellow] "
            f"Try: [cyan]pip install {pip_pkg}[/cyan]"
        )
        if not Confirm.ask("Continue anyway?", default=False):
            return None

    default_m = _default_model(slug)
    model_id = Prompt.ask("Model id", default=default_m).strip()
    if not model_id:
        console.print("[error]Model id is required.[/error]")
        return None

    ai_existing = base_cfg.get("ai", {}) if isinstance(base_cfg.get("ai"), dict) else {}
    yaml_keys = _existing_api_keys(ai_existing)
    api_keys: dict[str, str] = {}

    env_list = _env_keys_for_slug(slug)
    if slug in ("bedrock", "bedrock_converse", "anthropic_bedrock", "google_anthropic_vertex"):
        console.print(
            "[dim]This provider typically uses cloud IAM / default credentials "
            "(e.g. AWS CLI, GCP ADC). Leave secrets blank if already configured.[/dim]"
        )
    for env_name in env_list:
        if os.environ.get(env_name) or yaml_keys.get(env_name):
            continue
        val = Prompt.ask(
            f"Value for [cyan]{env_name}[/cyan] [dim](empty to skip)[/dim]",
            password=True,
            default="",
        ).strip()
        if val:
            api_keys[env_name] = val

    base_url_out: str | None = None
    if slug == "ollama":
        hint = os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
        bu = Prompt.ask("Ollama base URL", default=hint).strip() or hint
        base_url_out = bu
    elif slug in ("openai", "litellm") and Confirm.ask(
        "Custom API base URL / proxy? [dim](OpenAI-compatible)[/dim]", default=False
    ):
        bu = Prompt.ask("Base URL").strip()
        if bu:
            base_url_out = bu

    combined_model = f"{slug}:{model_id}"
    summary_lines = [
        f"  Provider: [green]{slug}[/green]",
        f"  Model:    [cyan]{combined_model}[/cyan]",
    ]
    if base_url_out:
        summary_lines.append(f"  Base URL: [cyan]{base_url_out}[/cyan]")
    if api_keys:
        summary_lines.append(
            "  API keys: " + ", ".join(f"[cyan]{k}[/cyan]=***" for k in sorted(api_keys))
        )
    console.print("\n[bold]Summary[/bold]\n" + "\n".join(summary_lines))

    if not Confirm.ask("\nProceed with this configuration?", default=True):
        return None

    patch: dict[str, Any] = {"model": combined_model}
    if base_url_out:
        patch["base_url"] = base_url_out
    if api_keys:
        merged_keys = {**yaml_keys, **api_keys}
        patch["api_keys"] = merged_keys

    return patch


def merge_wizard_patch_into_cfg(base_cfg: dict[str, Any], ai_patch: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge *ai_patch* into a copy of *base_cfg* under ``ai``."""
    cfg = copy.deepcopy(base_cfg)
    cfg.setdefault("ai", {})
    if not isinstance(cfg["ai"], dict):
        cfg["ai"] = {}
    from agloom_cli.config import _deep_merge

    _deep_merge(cfg["ai"], ai_patch)
    return cfg


def resolve_model_with_optional_wizard(
    console: Console,
    cfg: dict[str, Any],
    *,
    effective_model: str,
    provider: str | None,
    base_url: str | None,
    merge_yaml_provider: bool,
    no_provider_wizard: bool,
    llm_param_overrides: dict[str, Any] | None = None,
    llm_frozen: dict[str, Any] | None = None,
    thread_id: str | None = None,
) -> Any:
    """Call :func:`resolve_model`; on failure or no LLM in a TTY, run the provider wizard and retry."""
    from agloom_cli.config import (
        merge_ai_into_storage_yaml,
        merge_api_keys_into_session_json,
        resolve_model,
    )

    from .model_resolver import MissingProviderApiKey, MissingProviderDependency

    caught: BaseException | None = None
    try:
        llm = resolve_model(
            effective_model,
            config=cfg,
            provider=provider,
            base_url=base_url,
            merge_yaml_provider=merge_yaml_provider,
            llm_param_overrides=llm_param_overrides,
            llm_frozen=llm_frozen,
        )
        if llm is not None:
            return llm
    except (MissingProviderApiKey, MissingProviderDependency) as e:
        caught = e
        if no_provider_wizard or not _interactive_tty():
            raise
        console.print(f"[warning]{e}[/warning]")

    if no_provider_wizard or not _interactive_tty():
        if caught:
            raise caught
        return None

    patch = run_interactive_provider_wizard(console, cfg)
    if patch is None:
        if caught:
            raise caught
        return None

    merged = merge_wizard_patch_into_cfg(cfg, patch)
    tid_disp = f"{thread_id[:8]}…" if thread_id and len(thread_id) > 8 else (thread_id or "")
    patch_for_disk = augment_patch_api_keys_from_env(patch)
    if thread_id:
        if Confirm.ask(
            f"Save API keys to [path]this session's JSON[/path] "
            f"([cyan]sessions/{tid_disp}.json[/cyan] · ``model_binding.api_keys``)? "
            "[dim](recommended — does not change project defaults; model/provider are saved automatically per run)[/dim]",
            default=True,
        ):
            patch_keys = patch_for_disk.get("api_keys") if isinstance(patch_for_disk, dict) else None
            if isinstance(patch_keys, dict) and patch_keys:
                merge_api_keys_into_session_json(thread_id, patch_keys)
                console.print(f"[success]✓[/success] Saved API keys to [cyan]sessions/{tid_disp}.json[/cyan].")
            else:
                console.print("[dim]No API keys to save (none entered or all blank).[/dim]")
        if Confirm.ask(
            "Additionally save to [path]storage agloom.yaml[/path] as the default for "
            "[bold]all future sessions[/bold] in this project?",
            default=False,
        ):
            merge_ai_into_storage_yaml(patch_for_disk)
            console.print("[success]✓[/success] Saved to [cyan]agloom.yaml[/cyan] (project-wide default).")
    elif Confirm.ask(
        "Save provider, model, and api_keys to [path]agloom.yaml[/path] under this project?",
        default=True,
    ):
        merge_ai_into_storage_yaml(patch_for_disk)
        console.print("[success]✓[/success] Saved to [cyan]agloom.yaml[/cyan].")

    try:
        return resolve_model(
            patch.get("model", effective_model),
            config=merged,
            provider=provider,
            base_url=base_url or patch.get("base_url"),
            merge_yaml_provider=merge_yaml_provider,
            llm_param_overrides=llm_param_overrides,
            llm_frozen=llm_frozen,
        )
    except (MissingProviderApiKey, MissingProviderDependency) as e2:
        console.print(f"[error]Could not initialize the model after setup: {e2}[/error]")
        raise
