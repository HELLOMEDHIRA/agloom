"""Smart context injection with embeddings - for accurate, token-optimized queries."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .config import storage_dir

# Supported languages for chunking
LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "react",
    ".tsx": "react",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
}

# File patterns to ignore
IGNORE_PATTERNS = [
    "__pycache__",
    ".git",
    "node_modules",
    "venv",
    ".venv",
    ".agloom",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "coverage",
    ".pytest_cache",
    ".mypy_cache",
]


class FileChunk:
    """Represents a chunk of code (function, class, or code block)."""

    def __init__(
        self,
        name: str,
        type: str,  # function, class, method, code
        content: str,
        start_line: int,
        end_line: int,
        keywords: list[str],
    ):
        self.name = name
        self.type = type
        self.content = content
        self.start_line = start_line
        self.end_line = end_line
        self.keywords = keywords
        self.embedding: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "content": self.content,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "keywords": self.keywords,
            "embedding": self.embedding,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FileChunk:
        chunk = cls(
            data["name"],
            data["type"],
            data["content"],
            data["start_line"],
            data["end_line"],
            data["keywords"],
        )
        return chunk


class ProjectIndex:
    """Smart project index with embeddings and project structure."""

    def __init__(
        self,
        root: Path,
        chunks: list[FileChunk] | None = None,
        structure: dict | None = None,
        embeddings_data: dict | None = None,
    ):
        self.root = root
        self.root_hash = hashlib.md5(str(root.resolve()).encode(), usedforsecurity=False).hexdigest()[:8]
        self.chunks = chunks or []
        self.structure = structure or {}
        self.embeddings_data = embeddings_data or {}
        self._keyword_index: dict[str, list[int]] = {}

    def build_keyword_index(self) -> None:
        """Build keyword index for fast lookup."""
        self._keyword_index = {}
        for i, chunk in enumerate(self.chunks):
            for keyword in chunk.keywords:
                if keyword not in self._keyword_index:
                    self._keyword_index[keyword] = []
                self._keyword_index[keyword].append(i)

    def save(self, home_dir: Path | None = None) -> None:
        """Save index to disk."""

        home_dir = home_dir or storage_dir()
        index_dir = home_dir / "indexes"
        index_dir.mkdir(exist_ok=True)

        index_file = index_dir / f"{self.root_hash}.json"

        data = {
            "root": str(self.root),
            "root_hash": self.root_hash,
            "structure": self.structure,
            "chunks": [c.to_dict() for c in self.chunks],
            "embeddings": self.embeddings_data,
        }

        with open(index_file, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, root: Path, home_dir: Path | None = None) -> ProjectIndex | None:
        """Load index from disk if exists."""
        home_dir = home_dir or storage_dir()
        root_hash = hashlib.md5(str(root.resolve()).encode(), usedforsecurity=False).hexdigest()[:8]
        index_dir = home_dir / "indexes"
        index_file = index_dir / f"{root_hash}.json"

        if not index_file.exists():
            return None

        with open(index_file) as f:
            data = json.load(f)

        chunks = [FileChunk.from_dict(c) for c in data.get("chunks", [])]
        index = cls(
            root=Path(data["root"]),
            chunks=chunks,
            structure=data.get("structure", {}),
            embeddings_data=data.get("embeddings", {}),
        )
        index.build_keyword_index()
        return index


def extract_keywords(text: str) -> list[str]:
    """Extract keywords from code text."""
    keywords = set()

    # Extract function/class names
    keywords.update(re.findall(r"(?:def|class|async def)\s+(\w+)", text))

    # Extract decorators
    keywords.update(re.findall(r"@(\w+)", text))

    # Extract imports (findall with groups returns tuples, flatten them)
    for match in re.findall(r"from\s+(\w+)|import\s+(\w+)", text):
        keywords.update(part for part in match if part)

    # Extract common patterns
    keywords.update(re.findall(r"(\w+)_handler|\w+_callback", text))
    keywords.update(re.findall(r"on_(\w+)", text))

    # Clean and filter
    cleaned = []
    for kw in keywords:
        if len(kw) > 2 and kw not in ("self", "cls", "await", "async"):
            cleaned.append(kw.lower())

    return list(set(cleaned))[:10]


def chunk_python_file(content: str, file_path: Path) -> list[FileChunk]:
    """Chunk Python file into functions and classes."""
    chunks = []
    lines = content.split("\n")

    current_chunk: list[str] = []
    current_name = "module"
    current_type = "code"
    start_line = 1

    for i, line in enumerate(lines, 1):
        # Check for function definition
        func_match = re.match(r"(async\s+)?def\s+(\w+)\s*\(", line)
        if func_match:
            # Save previous chunk
            if current_chunk:
                chunks.append(
                    FileChunk(
                        name=current_name,
                        type=current_type,
                        content="\n".join(current_chunk).strip(),
                        start_line=start_line,
                        end_line=i - 1,
                        keywords=extract_keywords("\n".join(current_chunk)),
                    )
                )
            current_name = func_match.group(2)
            current_type = "function"
            start_line = i
            current_chunk = [line]
            continue

        # Check for class definition
        class_match = re.match(r"class\s+(\w+)(?:\(.*?\))?:", line)
        if class_match:
            if current_chunk:
                chunks.append(
                    FileChunk(
                        name=current_name,
                        type=current_type,
                        content="\n".join(current_chunk).strip(),
                        start_line=start_line,
                        end_line=i - 1,
                        keywords=extract_keywords("\n".join(current_chunk)),
                    )
                )
            current_name = class_match.group(1)
            current_type = "class"
            start_line = i
            current_chunk = [line]
            continue

        # Check for method (inside class)
        method_match = re.match(r"\s+(async\s+)?def\s+(\w+)\s*\(", line)
        if method_match and current_type == "class":
            chunks.append(
                FileChunk(
                    name=current_name,
                    type=current_type,
                    content="\n".join(current_chunk).strip(),
                    start_line=start_line,
                    end_line=i - 1,
                    keywords=extract_keywords("\n".join(current_chunk)),
                )
            )
            current_name = f"{current_name}.{method_match.group(2)}"
            current_type = "method"
            start_line = i
            current_chunk = [line]
            continue

        current_chunk.append(line)

    # Save last chunk
    if current_chunk:
        chunks.append(
            FileChunk(
                name=current_name,
                type=current_type,
                content="\n".join(current_chunk).strip(),
                start_line=start_line,
                end_line=len(lines),
                keywords=extract_keywords("\n".join(current_chunk)),
            )
        )

    return chunks


def chunk_file(content: str, file_path: Path) -> list[FileChunk]:
    """Chunk any file based on extension."""
    ext = file_path.suffix.lower()
    lang = LANGUAGE_EXTENSIONS.get(ext, "unknown")

    if lang == "python":
        return chunk_python_file(content, file_path)

    # Generic chunking for other languages
    return [
        FileChunk(
            name=file_path.stem,
            type="code",
            content=content[:5000],  # Limit size
            start_line=1,
            end_line=len(content.split("\n")),
            keywords=extract_keywords(content),
        )
    ]


def build_structure(root: Path) -> dict[str, Any]:
    """Build project structure tree."""
    structure = {"root": str(root), "files": {}, "dirs": {}}

    def should_ignore(path: Path) -> bool:
        return any(ignore in str(path) for ignore in IGNORE_PATTERNS)

    for path in root.rglob("*"):
        if should_ignore(path):
            continue
        if path.is_file():
            rel = path.relative_to(root)
            size = path.stat().st_size
            structure["files"][str(rel)] = {
                "size": size,
                "ext": path.suffix,
            }

    return structure


def build_index(
    root: Path,
    openai_client=None,
    force_rebuild: bool = False,
) -> ProjectIndex:
    """Build project index with chunks and embeddings."""

    # Check if index exists
    existing = ProjectIndex.load(root)
    if existing and not force_rebuild:
        return existing

    # Build structure
    structure = build_structure(root)

    # Chunk files
    chunks: list[FileChunk] = []
    for file_path, info in structure["files"].items():
        full_path = root / file_path
        if info["size"] > 100000:  # Skip files > 100KB
            continue

        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
            file_chunks = chunk_file(content, full_path)
            chunks.extend(file_chunks)
        except Exception:
            pass

    index = ProjectIndex(root=root, chunks=chunks, structure=structure)
    index.build_keyword_index()

    # Try to create embeddings
    if openai_client:
        try:
            _create_embeddings(index, openai_client)
        except Exception:
            pass
    else:
        # Try to import openai
        try:
            import openai

            openai_client = openai.OpenAI()
            _create_embeddings(index, openai_client)
        except Exception:
            pass

    return index


def _create_embeddings(index: ProjectIndex, client=None) -> None:
    """Create embeddings for chunks using BGE model (local, free)."""
    from sentence_transformers import SentenceTransformer

    texts = [f"{c.name}: {c.content[:500]}" for c in index.chunks]
    if not texts:
        return

    try:
        # Use BGE embeddings (local, free, no API key needed)
        model = SentenceTransformer("BAAI/bge-small-en-v1.5")
        embeddings = model.encode(texts, show_progress_bar=False)

        for i, chunk in enumerate(index.chunks):
            chunk.embedding = embeddings[i].tolist()

    except ImportError:
        # Fallback to OpenAI if BGE not installed
        if client:
            _create_embeddings_openai(index, client)
    except Exception:
        # Keyword fallback on error
        pass


def _create_embeddings_openai(index: ProjectIndex, client) -> None:
    """Create embeddings using OpenAI (fallback)."""

    texts = [f"{c.name}: {c.content[:500]}" for c in index.chunks]
    if not texts:
        return

    # Batch embedding creation
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )

    for i, chunk in enumerate(index.chunks):
        if i < len(response.data):
            chunk.embedding = response.data[i].embedding


def search_similar(
    index: ProjectIndex,
    query: str,
    top_k: int = 5,
) -> list[tuple[FileChunk, float]]:
    """Find most similar chunks to query."""

    # Extract keywords from query
    query_keywords = extract_keywords(query.lower())

    if not index.chunks:
        return []

    # Try BGE embeddings first (local, free)
    use_embeddings = any(c.embedding is not None for c in index.chunks)

    if use_embeddings and query_keywords:
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer("BAAI/bge-small-en-v1.5")
            query_embedding = model.encode([query])[0].tolist()

            # Calculate cosine similarity
            similarities = []
            for chunk in index.chunks:
                if chunk.embedding:
                    sim = _cosine_similarity(query_embedding, chunk.embedding)
                    similarities.append((chunk, sim))

            similarities.sort(key=lambda x: x[1], reverse=True)
            return similarities[:top_k]
        except Exception:
            pass

    # Fallback to keyword matching
    return keyword_search(index, query_keywords, top_k)


def keyword_search(
    index: ProjectIndex,
    keywords: list[str],
    top_k: int = 5,
) -> list[tuple[FileChunk, float]]:
    """Keyword-based search."""
    scores: dict[int, float] = {}

    for keyword in keywords:
        keyword_lower = keyword.lower()
        if keyword_lower in index._keyword_index:
            for chunk_idx in index._keyword_index[keyword_lower]:
                scores[chunk_idx] = scores.get(chunk_idx, 0) + 1

    if not scores:
        return [(index.chunks[i], 0.1) for i in range(min(top_k, len(index.chunks)))]

    # Sort by score
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [(index.chunks[idx], score / len(keywords)) for idx, score in sorted_scores[:top_k]]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a * mag_b == 0:
        return 0
    return dot / (mag_a * mag_b)


def get_smart_context(
    index: ProjectIndex,
    query: str,
    max_tokens: int = 2000,
) -> str:
    """Get optimized context for query."""
    similar = search_similar(index, query, top_k=3)

    if not similar:
        return ""

    context_parts = ["# Relevant code:\n"]

    used_tokens = 0
    for chunk, _score in similar:
        chunk_text = (
            f"\n## {chunk.name} ({chunk.type}, line {chunk.start_line}-{chunk.end_line})\n```{chunk.content[:500]}\n```"
        )

        if used_tokens + len(chunk_text) > max_tokens:
            break

        context_parts.append(chunk_text)
        used_tokens += len(chunk_text)

    return "".join(context_parts)


def refresh_index(project_path: Path | None = None) -> ProjectIndex:
    """Manually refresh project index."""
    from .project import detect_project

    if project_path:
        root = project_path
    else:
        ctx = detect_project()
        root = ctx.root

    return build_index(root, force_rebuild=True)


# Global index cache
_index_cache: dict[str, ProjectIndex] = {}


def get_index(project_path: Path | None = None) -> ProjectIndex:
    """Get or build project index."""
    from .project import detect_project

    if project_path:
        root = project_path
    else:
        ctx = detect_project()
        root = ctx.root

    root_str = str(root.resolve())

    if root_str in _index_cache:
        return _index_cache[root_str]

    index = build_index(root)
    _index_cache[root_str] = index
    return index
