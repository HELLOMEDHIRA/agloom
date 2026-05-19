"""``cli_workspace_prompt.txt`` and ``.agloom/agloom.yaml`` stay aligned."""

from __future__ import annotations

from pathlib import Path

import yaml

from agloom.prompts.core import CLI_WORKSPACE_SYSTEM_PROMPT
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
_PY_PROMPT = _REPO_ROOT / "agloom" / "prompts" / "cli_workspace_prompt.txt"
_CLI_PROMPT = _REPO_ROOT / "agloom_cli" / "prompts" / "cli_workspace_prompt.txt"


def test_prompt_txt_matches_python_constant() -> None:
    on_disk = _PY_PROMPT.read_text(encoding="utf-8")
    assert on_disk == CLI_WORKSPACE_SYSTEM_PROMPT


def test_agloom_cli_prompt_txt_matches_python_package() -> None:
    assert _CLI_PROMPT.is_file()
    assert _CLI_PROMPT.read_text(encoding="utf-8") == _PY_PROMPT.read_text(encoding="utf-8")


def test_default_agloom_yaml_embeds_canonical_system_prompt() -> None:
    data = yaml.safe_load(DEFAULT_AGLOOM_YAML)
    assert isinstance(data, dict)
    sp = extract_system_prompt_from_yaml(data)
    assert sp is not None
    assert is_canonical_cli_system_prompt(sp)


def test_yaml_indented_block_roundtrip() -> None:
    block = yaml_indented_block(CLI_WORKSPACE_SYSTEM_PROMPT)
    parsed = yaml.safe_load("system_prompt: |\n" + block)
    assert parsed["system_prompt"].strip() == CLI_WORKSPACE_SYSTEM_PROMPT.strip()


def test_migrate_legacy_system_prompt(tmp_path: Path) -> None:
    y = tmp_path / "agloom.yaml"
    y.write_text(
        "ai:\n  model: auto\n  system_prompt: |\n"
        "    You are an autonomous AI programming assistant built with agloom.\n\n"
        "    ## Your Capabilities\n\n"
        "    - File operations\n",
        encoding="utf-8",
    )
    assert is_legacy_cli_system_prompt(extract_system_prompt_from_yaml(yaml.safe_load(y.read_text())) or "")
    assert migrate_agloom_yaml_system_prompt(y) is True
    data = yaml.safe_load(y.read_text(encoding="utf-8"))
    sp = extract_system_prompt_from_yaml(data)
    assert sp is not None
    assert is_canonical_cli_system_prompt(sp)


def test_migrate_skips_missing_system_prompt(tmp_path: Path) -> None:
    y = tmp_path / "agloom.yaml"
    y.write_text("ai:\n  model: auto\n", encoding="utf-8")
    assert migrate_agloom_yaml_system_prompt(y) is False
    assert "system_prompt" not in y.read_text(encoding="utf-8")


def test_persist_user_system_prompt_roundtrip(tmp_path: Path) -> None:
    y = tmp_path / ".agloom" / "agloom.yaml"
    custom = "You are a strict reviewer. Be brief."
    assert persist_user_system_prompt_to_yaml(y, custom) is True
    data = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert extract_system_prompt_from_yaml(data) == custom
    assert is_user_tuned_system_prompt(custom)


def test_migrate_skips_custom_prompt(tmp_path: Path) -> None:
    y = tmp_path / "agloom.yaml"
    custom = "You are a billing-only assistant. Never touch infra."
    y.write_text(f"ai:\n  system_prompt: |\n    {custom}\n", encoding="utf-8")
    assert migrate_agloom_yaml_system_prompt(y) is False
    assert custom in y.read_text(encoding="utf-8")
