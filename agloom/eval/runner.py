"""Minimal eval harness: YAML cases, one ``ainvoke`` each, optional substring assert."""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from pathlib import Path

import yaml

from agloom import create_agent
from agloom.runtime.serve_cli import apply_api_key_env, resolve_llm_for_serve


async def _run_async(args: argparse.Namespace, path: Path) -> int:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases = raw.get("cases")
    if not isinstance(cases, list) or not cases:
        print("eval YAML must contain a non-empty list: cases:", file=sys.stderr)
        return 2

    seed = getattr(args, "eval_seed", None)
    if seed is not None:
        random.seed(seed)

    llm = resolve_llm_for_serve(args)
    if llm is None:
        print("No LLM resolved: set API keys or pass --model.", file=sys.stderr)
        return 1

    agent = await create_agent(model=llm, name="agloom-eval")
    keep_going = bool(getattr(args, "eval_keep_going", False))
    exit_code = 0

    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            print(f"case[{i}] must be a mapping", file=sys.stderr)
            return 2
        cid = str(case.get("id", f"case_{i}"))
        prompt = case.get("prompt") or case.get("query")
        if not isinstance(prompt, str) or not prompt.strip():
            print(f"{cid}: missing string prompt/query", file=sys.stderr)
            return 2
        expect = case.get("expect_substring") or case.get("expect")
        try:
            res = await agent.ainvoke(prompt.strip())
        except Exception as exc:
            print(f"FAIL {cid}: raised {type(exc).__name__}: {exc}", file=sys.stderr)
            exit_code = 1
            if not keep_going:
                await agent.aclose()
                return exit_code
            continue
        out = (res.output or "").strip()
        if expect is not None:
            if not isinstance(expect, str) or expect not in out:
                print(
                    f"FAIL {cid}: expected substring {expect!r} in output (got {out[:200]!r}…)",
                    file=sys.stderr,
                )
                exit_code = 1
                if not keep_going:
                    await agent.aclose()
                    return exit_code
                continue
        print(f"ok  {cid}")

    await agent.aclose()
    return exit_code


def run_eval_cli(args: argparse.Namespace) -> int:
    try:
        apply_api_key_env(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    path = Path(getattr(args, "eval_file", "eval.yaml")).expanduser().resolve()
    if not path.is_file():
        print(f"eval file not found: {path}", file=sys.stderr)
        return 2
    return asyncio.run(_run_async(args, path))
