"""Tests for agloom_cli — config, tool loader, filesystem tools (no API keys)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agloom_cli.config import (
    build_working_ai_for_thread,
    config_source_fingerprints,
    get_system_prompt,
    get_thread_id,
    list_project_cleanup_dirs,
    load_config,
    merge_ai_into_session_json,
    normalize_cli_session_id,
    read_session_model_binding,
    remove_project_cleanup_dirs,
    session_model_binding_is_usable,
    session_record_path,
    set_cli_project_root,
    start_new_session,
)
from agloom_cli.session_resume import (
    _cli_messages_to_turns,
    hydrate_repl_history_from_session_json,
)
from agloom_cli.tool_loader import discover_tools, tool
from agloom_cli.tools import read_file, write_file


def test_set_cli_project_root_creates_layout(tmp_path: Path) -> None:
    ag = set_cli_project_root(tmp_path)
    assert ag == tmp_path / ".agloom"
    assert (tmp_path / ".agloom" / "sessions").is_dir()
    assert (tmp_path / ".agloom" / "skills").is_dir()
    assert not (tmp_path / ".agloom" / "indexes").exists()
    assert (tmp_path / ".agloom" / "README.md").is_file()


def test_config_source_fingerprints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / ".agloom"
    store.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", store)
    y = store / "agloom.yaml"
    y.write_text("ai:\n  name: t\n", encoding="utf-8")
    fps = config_source_fingerprints(None)
    assert len(fps) == 1
    assert fps[0]["path"] == str(y.resolve())
    assert len(fps[0]["sha256"]) == 64


def test_start_new_session_preserves_history_and_sets_last_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / ".agloom"
    store.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", store)
    (store / "agloom.yaml").write_text("session:\n  current_session: 'abc'\n", encoding="utf-8")
    sid = "deadbeef"
    sf = store / "sessions" / f"{sid}.json"
    sf.parent.mkdir(parents=True)
    sf.write_text(
        '{"id":"deadbeef","started_at":"t0","turns":3,"messages":[{"role":"user","content":"hi"}]}',
        encoding="utf-8",
    )
    meta = {"at": "2026-01-01T00:00:00+00:00", "resolved": {"model": "groq:test"}}
    start_new_session(sid, run_metadata=meta)
    import json

    data = json.loads(sf.read_text(encoding="utf-8"))
    assert data["turns"] == 3
    assert len(data["messages"]) == 1
    assert data["last_run"] == meta
    assert "last_active" in data
    assert data.get("safety") == {"tool_allowlist": []}
    assert not (store / "sessions" / f"{sid}.yaml").is_file()


def test_remove_project_cleanup_dirs(tmp_path: Path) -> None:
    (tmp_path / ".agloom").mkdir()
    (tmp_path / ".agsuperbrain").mkdir()
    (tmp_path / ".agloom" / "agloom.yaml").write_text("ai:\n  name: x\n", encoding="utf-8")
    found = list_project_cleanup_dirs(tmp_path)
    assert {p.name for p in found} == {".agloom", ".agsuperbrain"}
    removed = remove_project_cleanup_dirs(tmp_path)
    assert len(removed) == 2
    assert not (tmp_path / ".agloom").exists()
    assert not (tmp_path / ".agsuperbrain").exists()


def test_load_config_coerces_legacy_require_approval_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / ".agloom"
    store.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", store)
    (store / "agloom.yaml").write_text(
        "safety:\n  require_approval: false\n  auto_approve: ''\n",
        encoding="utf-8",
    )
    cfg = load_config(None)
    assert cfg["safety"]["require_approval"] is True


def test_load_explicit_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate storage and project yaml so only the explicit file is merged."""
    isolated = tmp_path / "store"
    isolated.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", isolated)
    monkeypatch.setattr("agloom_cli.config.ProjectConfigPath", tmp_path / "no_project.yaml")
    cfg_path = tmp_path / "explicit.yaml"
    cfg_path.write_text("ai:\n  name: from-temp-file\n", encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.get("ai", {}).get("name") == "from-temp-file"


def test_load_missing_config_returns_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolated = tmp_path / "store"
    isolated.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", isolated)
    monkeypatch.setattr("agloom_cli.config.ProjectConfigPath", tmp_path / "no_project.yaml")
    cfg = load_config(Path("/non/existent/agloom-config-does-not-exist.yaml"))
    assert "ai" in cfg


def test_thread_id_from_config() -> None:
    cfg = {"session": {"current_session": "custom123"}}
    assert get_thread_id(cfg) == "custom123"


def test_thread_id_from_env() -> None:
    os.environ["AGLOOM_THREAD_ID"] = "env-thread"
    try:
        assert get_thread_id({}) == "env-thread"
    finally:
        del os.environ["AGLOOM_THREAD_ID"]


def test_thread_id_default_length() -> None:
    tid = get_thread_id({}, auto_save=False)
    assert len(tid) == 32
    int(tid, 16)


def test_normalize_cli_session_id_hex_and_uuid() -> None:
    assert normalize_cli_session_id("AbCdEf0123456789AbCdEf0123456789") == "abcdef0123456789abcdef0123456789"
    u = "550E8400-E29b-41D4-A716-446655440000"
    assert normalize_cli_session_id(u) == "550e8400e29b41d4a716446655440000"
    assert normalize_cli_session_id(f"  {u}  ") == "550e8400e29b41d4a716446655440000"


def test_normalize_cli_session_id_rejects_pathlike() -> None:
    with pytest.raises(ValueError, match="path"):
        normalize_cli_session_id("../evil")
    with pytest.raises(ValueError, match="path"):
        normalize_cli_session_id("bad/id")


def test_get_thread_id_hyphenated_uuid_from_config() -> None:
    cfg = {"session": {"current_session": "550E8400-E29b-41D4-A716-446655440000"}}
    assert get_thread_id(cfg) == "550e8400e29b41d4a716446655440000"


def test_get_thread_id_invalid_raises() -> None:
    cfg = {"session": {"current_session": "oops spaces"}}
    with pytest.raises(ValueError):
        get_thread_id(cfg)


def test_session_record_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", tmp_path)
    p = session_record_path("abc123")
    assert p == tmp_path / "sessions" / "abc123.json"


def test_cli_messages_to_turns_pairs_roles() -> None:
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "bye"},
    ]
    turns = _cli_messages_to_turns(msgs)
    assert turns[0]["q"] == "hi" and turns[0]["a"] == "hello"
    assert turns[1]["q"] == "bye" and "no assistant" in turns[1]["a"].lower()


class _FakeReplState:
    def __init__(self) -> None:
        self.turns: list[tuple[str, str]] = []

    def add_turn(self, query: str, output: str) -> None:
        self.turns.append((query, output))


def test_hydrate_repl_history_from_session_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / ".agloom"
    store.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", store)
    (store / "sessions").mkdir(parents=True)
    sid = "abc123"
    (store / "sessions" / f"{sid}.json").write_text(
        '{"id":"abc123","messages":['
        '{"role":"user","content":"hi"},'
        '{"role":"assistant","content":"hello"}'
        "]}",
        encoding="utf-8",
    )
    st = _FakeReplState()
    hydrate_repl_history_from_session_json(sid, st)
    assert st.turns == [("hi", "hello")]


def test_start_new_session_skip_config_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / ".agloom"
    store.mkdir()
    (store / "agloom.yaml").write_text("session:\n  current_session: 'keep-me'\n", encoding="utf-8")
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", store)
    start_new_session("brandnewid", update_config_current_session=False)
    txt = (store / "agloom.yaml").read_text(encoding="utf-8")
    assert "keep-me" in txt
    assert "brandnewid" not in txt
    assert not (store / "sessions" / "brandnewid.yaml").is_file()
    new_sess = json.loads((store / "sessions" / "brandnewid.json").read_text(encoding="utf-8"))
    assert new_sess.get("safety") == {"tool_allowlist": []}


def test_build_working_ai_session_overrides_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / ".agloom"
    store.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", store)
    sid = "c" * 32
    (store / "sessions").mkdir(parents=True)
    (store / "sessions" / f"{sid}.json").write_text(
        json.dumps(
            {
                "id": sid,
                "ai": {
                    "model": "groq:meta-llama/from-session",
                    "llm": {"temperature": 0.55, "top_p": 0.9},
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = {"ai": {"model": "openai:gpt-4o", "llm": {"temperature": 0, "max_tokens": 100}}}
    working, sess_only = build_working_ai_for_thread(cfg, sid)
    assert working["model"] == "groq:meta-llama/from-session"
    assert working["llm"]["temperature"] == 0.55
    assert working["llm"]["top_p"] == 0.9
    assert working["llm"]["max_tokens"] == 100
    assert sess_only["model"] == "groq:meta-llama/from-session"


def test_build_working_ai_migrates_legacy_yaml_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / ".agloom"
    store.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", store)
    sid = "d" * 32
    (store / "sessions").mkdir(parents=True)
    ypath = store / "sessions" / f"{sid}.yaml"
    ypath.write_text(
        "ai:\n  model: ollama:llama3.2\n  llm:\n    temperature: 0.3\n",
        encoding="utf-8",
    )
    cfg = {"ai": {"model": "openai:gpt-4o", "llm": {}}}
    working, sess_only = build_working_ai_for_thread(cfg, sid)
    assert not ypath.is_file()
    assert working["model"] == "ollama:llama3.2"
    assert working["llm"]["temperature"] == 0.3
    jpath = store / "sessions" / f"{sid}.json"
    assert jpath.is_file()
    migrated = json.loads(jpath.read_text(encoding="utf-8"))
    assert migrated["ai"]["model"] == "ollama:llama3.2"


def test_merge_ai_into_session_json_creates_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / ".agloom"
    store.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", store)
    (store / "sessions").mkdir(parents=True)
    sid = "e" * 32
    merge_ai_into_session_json(sid, {"model": "ollama:llama3.2", "llm": {"temperature": 0.3}})
    p = store / "sessions" / f"{sid}.json"
    assert p.is_file()
    loaded = json.loads(p.read_text(encoding="utf-8"))
    assert loaded["ai"]["model"] == "ollama:llama3.2"
    assert loaded["ai"]["llm"]["temperature"] == 0.3


def test_read_session_model_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / ".agloom"
    store.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", store)
    sid = "a" * 32
    (store / "sessions").mkdir(parents=True)
    sf = store / "sessions" / f"{sid}.json"
    sf.write_text(
        json.dumps({"id": sid, "model_binding": {"effective_model": "groq:meta-llama/foo"}}),
        encoding="utf-8",
    )
    b = read_session_model_binding(sid)
    assert b is not None
    assert b["effective_model"] == "groq:meta-llama/foo"
    assert session_model_binding_is_usable(b)
    assert not session_model_binding_is_usable({"effective_model": "auto"})


def test_start_new_session_writes_model_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / ".agloom"
    store.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", store)
    (store / "agloom.yaml").write_text("session:\n  current_session: 'x'\n", encoding="utf-8")
    sid = "b" * 32
    binding = {"effective_model": "openai:gpt-4o", "llm": {"temperature": 0}}
    start_new_session(sid, model_binding=binding, update_config_current_session=False)
    data = json.loads((store / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))
    assert data["model_binding"] == binding
    assert data.get("safety") == {"tool_allowlist": []}
    sess = data["ai"]
    assert sess["model"] == "openai:gpt-4o"
    assert sess["llm"]["temperature"] == 0
    assert "base_url" in sess
    assert sess["base_url"] is None
    assert not (store / "sessions" / f"{sid}.yaml").is_file()


def test_start_new_session_merges_model_binding_into_session_ai(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / ".agloom"
    store.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", store)
    (store / "sessions").mkdir(parents=True)
    sid = "f" * 32
    binding = {
        "effective_model": "nvidia:meta/Llama-4",
        "provider": "nvidia",
        "base_url": "https://example/v1",
        "merge_yaml_provider": True,
        "llm": {"temperature": 0.2, "top_p": 0.9},
    }
    start_new_session(sid, model_binding=binding, update_config_current_session=False)
    data = json.loads((store / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))
    ai = data["ai"]
    assert ai["model"] == "nvidia:meta/Llama-4"
    assert ai["provider"] == "nvidia"
    assert ai["base_url"] == "https://example/v1"
    assert ai["api_keys"] is None
    assert ai["llm"] == {"temperature": 0.2, "top_p": 0.9}


def test_start_new_session_session_ai_includes_api_keys_from_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / ".agloom"
    store.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", store)
    (store / "sessions").mkdir(parents=True)
    sid = "a" * 31 + "b"
    binding = {
        "effective_model": "nvidia:x",
        "provider": "nvidia",
        "base_url": None,
        "merge_yaml_provider": True,
        "llm": {},
        "api_keys": {"NVIDIA_API_KEY": "nvapi-test"},
    }
    start_new_session(sid, model_binding=binding, update_config_current_session=False)
    data = json.loads((store / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))
    assert data["ai"]["api_keys"] == {"NVIDIA_API_KEY": "nvapi-test"}


def test_start_new_session_session_ai_null_base_url_when_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / ".agloom"
    store.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", store)
    (store / "sessions").mkdir(parents=True)
    sid = "f" * 32
    (store / "sessions" / f"{sid}.json").write_text(
        json.dumps({"id": sid, "ai": {"model": "nvidia:meta/foo", "llm": {"temperature": 0}}}),
        encoding="utf-8",
    )
    binding = {
        "effective_model": "nvidia:meta/foo",
        "provider": "nvidia",
        "base_url": None,
        "merge_yaml_provider": True,
        "llm": {"temperature": 0},
    }
    start_new_session(sid, model_binding=binding, update_config_current_session=False)
    loaded = json.loads((store / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))["ai"]
    assert "base_url" in loaded
    assert loaded["base_url"] is None


def test_get_system_prompt_nonempty() -> None:
    prompt = get_system_prompt()
    assert "autonomous" in prompt
    assert "programming" in prompt


def test_discover_tools_empty_dir(tmp_path: Path) -> None:
    assert discover_tools(tmp_path) == []


def test_discover_tools_nonexistent() -> None:
    assert discover_tools(Path("/nonexistent-agloom-tools-path")) == []


def test_tool_decorator_marks_function() -> None:
    @tool
    async def sample_tool(x: str) -> str:
        return x

    assert getattr(sample_tool, "_tool_marker", False) is True


@pytest.mark.asyncio
async def test_read_file_tool(tmp_path: Path) -> None:
    p = tmp_path / "hello.txt"
    p.write_text("Hello World", encoding="utf-8")
    result = await read_file(str(p))
    assert "Hello World" in result


@pytest.mark.asyncio
async def test_write_file_tool(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    result = await write_file(str(target), "Test content")
    assert "Successfully wrote" in result
    assert target.exists()
