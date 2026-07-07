"""Runtime maps YAML/argv into create_agent kwargs (not AGLOOM_* env)."""

from __future__ import annotations

from argparse import Namespace

from agloom.runtime.serve_cli import (
    build_create_agent_kwargs,
    harness_metadata_from_args,
    merge_agloom_yaml_into_namespace,
)


def test_build_create_agent_kwargs_execution_fields() -> None:
    args = Namespace(
        session_max_turns=50,
        require_tool_approval=True,
        llm_timeout=800.0,
        turn_planner_timeout=120.0,
        react_graph_timeout=900.0,
        react_recursion_limit=50,
        max_concurrent=8,
        max_retries=3,
        enable_memory_tools=False,
    )
    kw = build_create_agent_kwargs(args)
    assert kw["llm_timeout"] == 800.0
    assert kw["turn_planner_timeout"] == 120.0
    assert kw["react_graph_timeout"] == 900.0
    assert kw["react_recursion_limit"] == 50
    assert kw["max_concurrent"] == 8
    assert kw["max_retries"] == 3
    assert kw["enable_memory_tools"] is False


def test_harness_metadata_from_args() -> None:
    args = Namespace(harness_project_name="my-platform", harness_goal="Find root cause")
    meta = harness_metadata_from_args(args)
    assert meta is not None
    assert meta.project_name == "my-platform"
    assert meta.goal == "Find root cause"


def test_merge_agloom_yaml_into_namespace(tmp_path) -> None:
    agloom_dir = tmp_path / ".agloom"
    agloom_dir.mkdir()
    (agloom_dir / "agloom.yaml").write_text(
        """
execution:
  llm_timeout: 45.0
  classifier_timeout: 9.0
harness:
  enabled: false
  project_name: yaml-project
  goal: From yaml
""",
        encoding="utf-8",
    )
    args = Namespace(no_harness=False, require_tool_approval=None)
    merge_agloom_yaml_into_namespace(args, cwd=tmp_path)
    assert args.llm_timeout == 45.0
    assert args.turn_planner_timeout == 9.0
    assert args.harness_project_name == "yaml-project"
    assert args.harness_goal == "From yaml"
    assert args.no_harness is True


def test_session_snapshot_includes_execution_fields() -> None:
    from agloom.runtime.serve_cli import session_started_snapshot_from_args

    args = Namespace(
        session_max_turns=50,
        require_tool_approval=True,
        llm_timeout=800.0,
        turn_planner_timeout=120.0,
        harness_project_name="my-platform",
        no_harness=False,
    )
    snap = session_started_snapshot_from_args(args)
    eff = snap["effective_config"]
    assert eff["llm_timeout"] == 800.0
    assert eff["turn_planner_timeout"] == 120.0
    assert eff["harness_project_name"] == "my-platform"
