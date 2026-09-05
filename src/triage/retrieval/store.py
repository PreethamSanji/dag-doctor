"""Vector stores.

The retrieval corpus is indexed once and queried per triage run. Two backends
share one interface so the agent never knows which is behind it:

``memory``
    A JSON-file index. No services required, deterministic, and fast enough for
    a vendored corpus of a few hundred documents. This is what CI uses.

``pgvector``
    Postgres with the ``vector`` extension (docker compose service ``db``).
    Added in M2; see :mod:`triage.retrieval.pgvector_store`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from triage.retrieval.chunking import Chunk
from triage.retrieval.embeddings import Embedder, cosine

DEFAULT_INDEX_PATH = Path(".triage/index.json")


@dataclass(frozen=True)
class SearchResult:
    """A retrieved chunk and its similarity to the query."""

    chunk: Chunk
    score: float


class VectorStore(Protocol):
    """Indexing and querying, independent of the storage engine."""

    def rebuild(self, chunks: list[Chunk], embedder: Embedder) -> int: ...

    def search(self, query: str, embedder: Embedder, k: int = 6) -> list[SearchResult]: ...

    def count(self) -> int: ...


def _chunk_to_row(chunk: Chunk, vector: list[float]) -> dict[str, object]:
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "text": chunk.text,
        "source": chunk.source,
        "source_url": chunk.source_url,
        "license": chunk.license,
        "title": chunk.title,
        "ordinal": chunk.ordinal,
        "embedding": vector,
    }


def _row_to_chunk(row: dict) -> Chunk:
    return Chunk(
        chunk_id=row["chunk_id"],
        doc_id=row["doc_id"],
        text=row["text"],
        source=row["source"],
        source_url=row["source_url"],
        license=row["license"],
        title=row["title"],
        ordinal=int(row["ordinal"]),
    )


class MemoryStore:
    """JSON-backed index. Loads lazily; writes atomically on rebuild."""

    def __init__(self, path: Path | str = DEFAULT_INDEX_PATH) -> None:
        self.path = Path(path)
        self._rows: list[dict] | None = None

    @property
    def rows(self) -> list[dict]:
        if self._rows is None:
            self._rows = self._load()
        return self._rows

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return payload.get("rows", [])

    def rebuild(self, chunks: list[Chunk], embedder: Embedder) -> int:
        vectors = embedder.embed([chunk.text for chunk in chunks])
        rows = [_chunk_to_row(chunk, vector) for chunk, vector in zip(chunks, vectors, strict=True)]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"embedder": embedder.name, "dim": embedder.dim, "rows": rows}),
            encoding="utf-8",
        )
        tmp.replace(self.path)
        self._rows = rows
        return len(rows)

    def search(self, query: str, embedder: Embedder, k: int = 6) -> list[SearchResult]:
        if not self.rows:
            return []
        query_vector = embedder.embed([query])[0]
        scored = [
            SearchResult(chunk=_row_to_chunk(row), score=cosine(query_vector, row["embedding"]))
            for row in self.rows
        ]
        scored.sort(key=lambda result: (-result.score, result.chunk.chunk_id))
        return scored[:k]

    def count(self) -> int:
        return len(self.rows)


def build_store(kind: str, *, database_url: str = "", index_path: Path | str | None = None):
    """Construct the store named in config."""
    if kind == "memory":
        return MemoryStore(index_path or DEFAULT_INDEX_PATH)
    if kind == "pgvector":
        from triage.retrieval.pgvector_store import PgVectorStore

        return PgVectorStore(database_url)
    raise ValueError(f"unknown store: {kind!r} (expected 'memory' or 'pgvector')")
