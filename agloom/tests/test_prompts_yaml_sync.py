"""YAML system_prompt helpers (core package — no CLI prompt file here)."""

from __future__ import annotations

from pathlib import Path

import yaml

from agloom.prompts.yaml_sync import (
    extract_system_prompt_from_yaml,
    is_canonical_cli_system_prompt,
    is_legacy_cli_system_prompt,
    is_user_tuned_system_prompt,
    migrate_agloom_yaml_system_prompt,
    persist_user_system_prompt_to_yaml,
    yaml_indented_block,
)
from agloom.runtime.workspace_bootstrap import DEFAULT_AGLOOM_YAML

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_PROMPT = _REPO_ROOT / "agloom_cli" / "prompts" / "cli_workspace_prompt.txt"


def test_cli_prompt_txt_lives_in_agloom_cli_only() -> None:
    assert _CLI_PROMPT.is_file()
    assert "terminal workspace (agloom cli)" in _CLI_PROMPT.read_text(encoding="utf-8").lower()


def test_default_agloom_yaml_has_no_embedded_system_prompt() -> None:
    data = yaml.safe_load(DEFAULT_AGLOOM_YAML)
    assert isinstance(data, dict)
    assert extract_system_prompt_from_yaml(data) is None


def test_yaml_indented_block_roundtrip() -> None:
    sample = "You are a test assistant.\nLine two.\n"
    block = yaml_indented_block(sample)
    parsed = yaml.safe_load("system_prompt: |\n" + block)
    assert parsed["system_prompt"].strip() == sample.strip()


def test_canonical_marker_detection() -> None:
    canonical = "You are the terminal workspace (agloom cli) agent.\n"
    assert is_canonical_cli_system_prompt(canonical)
    assert not is_legacy_cli_system_prompt(canonical)


def test_migrate_is_noop_in_core() -> None:
    y = Path(__file__).parent / "_noop_migrate.yaml"
    try:
        y.write_text(
            "ai:\n  system_prompt: |\n    built with agloom\n    ## Your Capabilities\n",
            encoding="utf-8",
        )
        assert migrate_agloom_yaml_system_prompt(y) is False
        assert "built with agloom" in y.read_text(encoding="utf-8")
    finally:
        if y.is_file():
            y.unlink()


def test_persist_user_system_prompt_roundtrip(tmp_path: Path) -> None:
    y = tmp_path / ".agloom" / "agloom.yaml"
    custom = "You are a strict reviewer. Be brief."
    assert persist_user_system_prompt_to_yaml(y, custom) is True
    data = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert extract_system_prompt_from_yaml(data) == custom
    assert is_user_tuned_system_prompt(custom)
