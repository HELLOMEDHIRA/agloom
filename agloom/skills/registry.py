"""LongTermStore-backed skill registry with bootstrap and runtime access."""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC
from pathlib import Path
from typing import Any

from ..logging_utils import get_logger
from .skill import (
    SkillContent,
    SkillManifest,
    erase_skill_md_tree,
    load_skill_content,
    parse_skill_md,
    write_skill_md,
)

logger = get_logger(__name__)

_disk_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="skill-io")

GLOBAL_NS = ("skills", "global")
BOOTSTRAP_KEY = "__bootstrapped__"


def _is_skill_sentinel(meta: dict) -> bool:
    """True for bootstrap/model-fingerprint rows, not user skills."""
    name = str(meta.get("name") or meta.get("skill_name") or "")
    if name.startswith("__"):
        return True
    if meta.get("bootstrapped"):
        return True
    return False


def _skill_content_fingerprint(description: str, body: str) -> str:
    raw = f"{description.strip()}\n{body.strip()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


_DEFAULT_SKILL_DIRS = [
    ".agent/skills",
    ".claude/skills",
    ".github/skills",
    "skills",
]


class SkillRegistry:
    """Process-safe skill registry backed by LongTermStore."""

    def __init__(self, store: Any, agent_name: str, *, disk_mirror: Path | None = None) -> None:
        self._store = store
        self._agent_name = agent_name
        self._agent_ns = ("skills", agent_name)
        self._disk_mirror = disk_mirror.resolve() if disk_mirror is not None else None
        self._cache: dict[str, SkillContent] = {}
        self._cache_lock = asyncio.Lock()

    async def bootstrap(
        self,
        skill_dirs: list[str] | None = None,
        force: bool = False,
    ) -> int:
        """Parse SKILL.md files from disk into LTS. Idempotent via sentinel key."""
        if not force:
            sentinel = await self._lts_get(GLOBAL_NS, BOOTSTRAP_KEY)
            if sentinel is not None:
                logger.debug(f"SkillRegistry [{self._agent_name}]: global bootstrap already done — skip")
                return 0

        loop = asyncio.get_running_loop()
        dirs = [Path(d) for d in (skill_dirs or _resolve_skill_dirs())]
        written = 0

        def _scan_disk(dirs: list[Path]) -> list[tuple[Path, SkillManifest, SkillContent]]:
            """Sync disk scan — runs in a thread to avoid blocking the event loop."""
            found = []
            for base in dirs:
                if not base.exists():
                    continue
                for skill_file in sorted(base.rglob("SKILL.md")):
                    manifest = parse_skill_md(skill_file)
                    if not manifest:
                        continue
                    content = load_skill_content(manifest)
                    found.append((skill_file, manifest, content))
            return found

        disk_results = await loop.run_in_executor(_disk_pool, _scan_disk, dirs)

        for skill_file, manifest, content in disk_results:
            existing = await self._lts_get(GLOBAL_NS, manifest.name)
            if existing and not force:
                logger.debug(f"SkillRegistry: '{manifest.name}' already in LTS — skip")
                continue

            await self._lts_save(
                ns=GLOBAL_NS,
                key=manifest.name,
                index=_build_index_text(manifest, content),
                metadata=content.to_lts_metadata(),
            )
            written += 1
            logger.info(f"SkillRegistry [{self._agent_name}]: bootstrapped '{manifest.name}' from {skill_file}")

        await self._lts_save(
            ns=GLOBAL_NS,
            key=BOOTSTRAP_KEY,
            index="bootstrap-sentinel",
            metadata={"bootstrapped": True, "written": written},
        )
        logger.info(f"SkillRegistry [{self._agent_name}]: bootstrap complete — {written} skill(s) written to LTS")
        return written

    async def reset_bootstrap(self) -> None:
        """Clear bootstrap sentinel so next call re-parses all SKILL.md files."""
        await self._store.adelete(GLOBAL_NS, BOOTSTRAP_KEY)
        self._cache.clear()
        logger.info(f"SkillRegistry [{self._agent_name}]: bootstrap sentinel cleared")

    async def list_manifests(self) -> list[SkillManifest]:
        """Return all manifests (global + agent). Agent-specific overrides global on collision."""
        merged: dict[str, SkillManifest] = {}

        global_results = await self._store.asearch(
            namespace=GLOBAL_NS,
            query="skill",
            top_k=100,
        )
        for r in global_results:
            meta = _meta(r)
            if _is_skill_sentinel(meta):
                continue
            m = SkillManifest.from_metadata(meta)
            if m:
                merged[m.name] = m

        agent_results = await self._store.asearch(
            namespace=self._agent_ns,
            query="skill",
            top_k=100,
        )
        for r in agent_results:
            meta = _meta(r)
            if _is_skill_sentinel(meta):
                continue
            m = SkillManifest.from_metadata(meta)
            if m:
                merged[m.name] = m

        return list(merged.values())

    async def get_content(self, name: str) -> SkillContent | None:
        """Load full skill content from LTS. Checks cache → agent ns → global ns."""
        async with self._cache_lock:
            if name in self._cache:
                return self._cache[name]

        content = await self._fetch_content(self._agent_ns, name)
        if content is None:
            content = await self._fetch_content(GLOBAL_NS, name)

        if content is None:
            logger.warning(f"SkillRegistry [{self._agent_name}]: skill '{name}' not found in LTS")
            return None

        async with self._cache_lock:
            self._cache[name] = content
        logger.debug(f"SkillRegistry [{self._agent_name}]: loaded '{name}' ({len(content.body)} body chars)")
        return content

    async def search_skills(
        self,
        query: str,
        top_k: int = 3,
    ) -> list[SkillManifest]:
        """Semantic search across both namespaces; returns manifests only."""
        seen: dict[str, SkillManifest] = {}

        for ns in (self._agent_ns, GLOBAL_NS):
            results = await self._store.asearch(
                namespace=ns,
                query=query,
                top_k=top_k,
            )
            for r in results:
                meta = _meta(r)
                if _is_skill_sentinel(meta):
                    continue
                m = SkillManifest.from_metadata(meta)
                if m and m.name not in seen:
                    seen[m.name] = m

        return list(seen.values())[:top_k]

    async def save_learned_skill(
        self,
        name: str,
        description: str,
        body: str,
        scope: str = "global",
        tags: list[str] | None = None,
        skill_data: dict | None = None,
    ) -> None:
        """Persist a learned skill to LTS (global or agent-scoped). Auto-increments version on overwrite.

        Near-duplicate bodies (same SHA-256 of description+body) reuse the existing store key
        even if *name* differs slightly, to avoid proliferating learned skills.
        """
        ns = GLOBAL_NS if scope == "global" else self._agent_ns

        fp = _skill_content_fingerprint(description, body)
        canon_name = name
        try:
            candidates = await self._store.asearch(ns, query=description[:120], top_k=20)
        except Exception as exc:
            logger.debug(f"SkillRegistry [{self._agent_name}]: dedupe search skipped: {exc!r}")
            candidates = []
        for r in candidates:
            meta = _meta(r)
            if _is_skill_sentinel(meta):
                continue
            if meta.get("content_fingerprint") == fp and meta.get("name"):
                canon_name = str(meta["name"])
                if canon_name != name:
                    logger.info(
                        f"SkillRegistry [{self._agent_name}]: deduping learned skill "
                        f"{name!r} → existing {canon_name!r} (matching content fingerprint)"
                    )
                break

        name = canon_name

        prev_version = 0
        existing_meta = await self._fetch_raw_meta(ns, name)
        if existing_meta:
            prev_version = existing_meta.get("version", 0)

        manifest = SkillManifest(
            name=name,
            description=description,
            scope=scope,
            source="learned",
            tags=tags or ["learned"],
            version=prev_version + 1,
        )
        metadata = {
            **manifest.to_metadata(),
            "body": body,
            "skill_data": skill_data or {},
            "content_fingerprint": fp,
        }
        await self._lts_save(
            ns=ns,
            key=name,
            index=(f"learned-skill:{name} | {description} | {body[:200]}"),
            metadata=metadata,
        )
        if self._disk_mirror is not None:
            try:
                write_skill_md(self._disk_mirror, manifest, body, skill_data=skill_data)
            except OSError as exc:
                logger.warning(
                    f"SkillRegistry [{self._agent_name}]: could not mirror skill '{name}' to disk: {exc}"
                )
        async with self._cache_lock:
            self._cache.pop(name, None)
        logger.info(f"SkillRegistry [{self._agent_name}]: saved learned skill '{name}' → ns={ns}")

    async def remove_skill_at(self, ns: tuple, name: str) -> None:
        """Delete a skill from the store and optional disk mirror (internal / lifecycle)."""
        await self._store.adelete(ns, name)
        async with self._cache_lock:
            self._cache.pop(name, None)
        self._erase_disk_skill(name)

    async def remove_skill(self, name: str, scope: str = "global") -> bool:
        """Delete skill by name and scope. Returns False if not found in store."""
        ns = GLOBAL_NS if scope == "global" else self._agent_ns
        if await self._fetch_raw_meta(ns, name) is None:
            return False
        await self.remove_skill_at(ns, name)
        return True

    def _erase_disk_skill(self, name: str) -> None:
        if self._disk_mirror is None:
            return
        try:
            erase_skill_md_tree(self._disk_mirror, name)
        except OSError as exc:
            logger.warning(
                f"SkillRegistry [{self._agent_name}]: could not remove skill '{name}' from disk: {exc}"
            )

    async def update_skill_usage(
        self,
        name: str,
        success: bool,
    ) -> None:
        """Increment success/failure count and re-save; prune if confidence too low."""
        content = await self.get_content(name)
        if not content:
            return
        meta = await self._fetch_raw_meta(self._agent_ns, name) or await self._fetch_raw_meta(GLOBAL_NS, name)
        if not meta:
            return

        skill_data = meta.get("skill_data", {})
        if not skill_data:
            return

        try:
            from datetime import datetime

            from .skill import AgentSkill

            skill = AgentSkill(**skill_data)
            if success:
                skill.success_count += 1
            else:
                skill.failure_count += 1
            skill.last_used = datetime.now(UTC).isoformat()

            if skill.should_prune():
                ns = GLOBAL_NS if skill.scope == "global" else self._agent_ns
                await self.remove_skill_at(ns, name)
                logger.info(
                    f"SkillRegistry [{self._agent_name}]: "
                    f"pruned low-confidence skill '{name}' "
                    f"(confidence={skill.confidence():.0%})"
                )
                return

            await self.save_learned_skill(
                name=skill.name,
                description=skill.description,
                body=skill.to_content_body(),
                scope=skill.scope,
                tags=["learned", skill.pattern.lower()],
                skill_data=skill.model_dump(),
            )
        except Exception as e:
            logger.warning(f"SkillRegistry [{self._agent_name}]: update_skill_usage failed for '{name}': {e}")

    async def classifier_block(self) -> str:
        """Build classifier prompt block listing all skill names + descriptions."""
        manifests = await self.list_manifests()
        if not manifests:
            return ""
        lines = "\n".join(m.classifier_line() for m in manifests)
        return "Available skills (call load_skill tool to get full instructions):\n" + lines

    async def _lts_save(
        self,
        ns: tuple,
        key: str,
        index: str,
        metadata: dict,
    ) -> None:
        await self._store.asave(
            namespace=ns,
            key=key,
            value=index,
            metadata=metadata,
        )

    async def _lts_get(self, ns: tuple, key: str) -> Any | None:
        try:
            return await self._store.aget(ns, key)
        except Exception:
            return None

    async def _fetch_content(self, ns: tuple, name: str) -> SkillContent | None:
        meta = await self._fetch_raw_meta(ns, name)
        if not meta:
            return None
        return SkillContent.from_lts_metadata(meta)

    async def _fetch_raw_meta(self, ns: tuple, name: str) -> dict | None:
        result = await self._lts_get(ns, name)
        if result:
            return _meta(result)
        # Narrow semantic lookup when aget(key) returns nothing.
        results = await self._store.asearch(
            namespace=ns,
            query=f"skill:{name}",
            top_k=1,
        )
        if results:
            m = _meta(results[0])
            if m.get("name") == name:
                return m
        return None


def _meta(record: Any) -> dict:
    return getattr(record, "value", {}) or {}


def _build_index_text(manifest: SkillManifest, content: SkillContent) -> str:
    return (
        f"skill:{manifest.name} | "
        f"tags:{manifest.tags} | "
        f"description:{manifest.description} | "
        f"body_preview:{content.body[:200]}"
    )


_cached_skill_dirs: list[str] | None = None
_EXTRA_SKILL_DIRS: list[str] = []
_skill_dirs_cache_lock = threading.Lock()


def set_extra_skill_dirs(dirs: list[str] | None) -> None:
    """Prepend these directories to skill bootstrap search (e.g. ``<project>/.agloom/skills``)."""
    global _cached_skill_dirs, _EXTRA_SKILL_DIRS
    with _skill_dirs_cache_lock:
        _EXTRA_SKILL_DIRS = list(dirs or [])
        _cached_skill_dirs = None


def _resolve_skill_dirs() -> list[str]:
    global _cached_skill_dirs
    with _skill_dirs_cache_lock:
        if _cached_skill_dirs is not None:
            return _cached_skill_dirs

        dirs: list[str] = []
        dirs.extend(_EXTRA_SKILL_DIRS)
        if env_dir := os.environ.get("AGENT_SKILLS_DIR"):
            dirs.append(env_dir)
        dirs.extend(_DEFAULT_SKILL_DIRS)

        pkg_skills = Path(__file__).parent.parent / "bundled_skills"
        if pkg_skills.exists():
            dirs.append(str(pkg_skills))

        _cached_skill_dirs = dirs
        return dirs
