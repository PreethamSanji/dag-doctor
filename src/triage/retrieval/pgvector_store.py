"""pgvector-backed vector store (M2).

Postgres with the ``vector`` extension, which is what ``docker compose up -d``
provisions as the ``db`` service. Same interface as
:class:`~triage.retrieval.store.MemoryStore`, so the agent never knows which is
behind it and CI can keep using the file-backed one.

The embedding column is sized from the embedder at rebuild time. Changing the
embedder or its dimension therefore rebuilds the table - which is correct, since
vectors from two different embedders are not comparable.
"""

from __future__ import annotations

from typing import Any

import psycopg

from triage.retrieval.chunking import Chunk
from triage.retrieval.embeddings import Embedder
from triage.retrieval.store import SearchResult

TABLE = "triage_chunks"

_CREATE = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS {table} (
    chunk_id    text PRIMARY KEY,
    doc_id      text NOT NULL,
    source      text NOT NULL,
    source_url  text NOT NULL,
    license     text NOT NULL,
    title       text NOT NULL,
    ordinal     integer NOT NULL,
    text        text NOT NULL,
    embedder    text NOT NULL,
    embedding   vector({dim}) NOT NULL
);
"""

# Cosine distance; the ivfflat index needs the matching operator class.
_INDEX = """
CREATE INDEX IF NOT EXISTS {table}_embedding_idx
    ON {table} USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
"""

_SEARCH = """
SELECT chunk_id, doc_id, source, source_url, license, title, ordinal, text,
       1 - (embedding <=> %s::vector) AS score
FROM {table}
ORDER BY embedding <=> %s::vector
LIMIT %s;
"""


def _vector_literal(vector: list[float]) -> str:
    """pgvector accepts a bracketed literal; psycopg has no native adapter for it."""
    return "[" + ",".join(f"{value:.7g}" for value in vector) + "]"


class PgVectorStore:
    """Indexing and querying against Postgres + pgvector."""

    def __init__(self, database_url: str, *, table: str = TABLE) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is required for the pgvector store")
        self._url = database_url
        self._table = table

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._url)

    def rebuild(self, chunks: list[Chunk], embedder: Embedder) -> int:
        """Replace the whole index. Atomic: one transaction, truncate then insert."""
        vectors = embedder.embed([chunk.text for chunk in chunks])
        rows: list[tuple[Any, ...]] = [
            (
                chunk.chunk_id,
                chunk.doc_id,
                chunk.source,
                chunk.source_url,
                chunk.license,
                chunk.title,
                chunk.ordinal,
                chunk.text,
                embedder.name,
                _vector_literal(vector),
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]

        with self._connect() as conn, conn.cursor() as cur:
            # A dimension change means the old vectors are meaningless, so the
            # table is dropped rather than migrated.
            cur.execute(f"DROP TABLE IF EXISTS {self._table};")
            cur.execute(_CREATE.format(table=self._table, dim=embedder.dim))
            cur.executemany(
                f"INSERT INTO {self._table} (chunk_id, doc_id, source, source_url, "
                f"license, title, ordinal, text, embedder, embedding) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)",
                rows,
            )
            cur.execute(_INDEX.format(table=self._table))
            conn.commit()
        return len(rows)

    def search(self, query: str, embedder: Embedder, k: int = 6) -> list[SearchResult]:
        vector = _vector_literal(embedder.embed([query])[0])
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(_SEARCH.format(table=self._table), (vector, vector, k))
            rows = cur.fetchall()
        return [
            SearchResult(
                chunk=Chunk(
                    chunk_id=row[0],
                    doc_id=row[1],
                    source=row[2],
                    source_url=row[3],
                    license=row[4],
                    title=row[5],
                    ordinal=row[6],
                    text=row[7],
                ),
                score=float(row[8]),
            )
            for row in rows
        ]

    def count(self) -> int:
        """Chunk count, or zero when the table has not been built yet."""
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(f"SELECT count(*) FROM {self._table};")
                row = cur.fetchone()
                return int(row[0]) if row else 0
        except psycopg.Error:
            return 0
