"""pgvector store, exercised against a live Postgres when one is reachable.

Skipped by default so ``make check`` stays offline and free. Run it with the
compose stack up:

    docker compose up -d db
    DATABASE_URL=postgresql://triage:triage@localhost:5432/triage uv run pytest -m pgvector
"""

from __future__ import annotations

import os

import pytest

from triage.retrieval.chunking import chunk_corpus
from triage.retrieval.corpus import load_corpus
from triage.retrieval.embeddings import HashingEmbedder

pytestmark = [pytest.mark.integration, pytest.mark.pgvector]

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _reachable(url: str) -> bool:
    if not url:
        return False
    import psycopg

    try:
        with psycopg.connect(url, connect_timeout=3):
            return True
    except psycopg.Error:
        return False


pytestmark.append(
    pytest.mark.skipif(
        not _reachable(DATABASE_URL),
        reason="no reachable DATABASE_URL; run `docker compose up -d db`",
    )
)


@pytest.fixture
def store():
    from triage.retrieval.pgvector_store import PgVectorStore

    return PgVectorStore(DATABASE_URL, table="triage_chunks_test")


def test_rebuild_then_search_ranks_the_right_document(store):
    embedder = HashingEmbedder(dim=512)
    chunks = chunk_corpus(load_corpus("corpus"), chunk_tokens=320, chunk_overlap=60)

    assert store.rebuild(chunks, embedder) == len(chunks)
    assert store.count() == len(chunks)

    results = store.search("Negsignal.SIGKILL no traceback OOM killer", embedder, k=3)

    assert len(results) == 3
    assert results[0].score >= results[-1].score
    assert any("SIGKILL" in result.chunk.text for result in results)
    # Provenance must survive the round trip; citations depend on it.
    assert all(result.chunk.source_url for result in results)


def test_rebuild_is_idempotent(store):
    embedder = HashingEmbedder(dim=512)
    chunks = chunk_corpus(load_corpus("corpus"), chunk_tokens=320, chunk_overlap=60)

    first = store.rebuild(chunks, embedder)
    second = store.rebuild(chunks, embedder)

    assert first == second == store.count()
