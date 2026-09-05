"""The retrieval facade the rest of the system uses.

Ties config to an embedder and a store, and hands back chunks that carry their
own provenance so citations can be validated later.
"""

from __future__ import annotations

from pathlib import Path

from triage.config import Config
from triage.retrieval.chunking import chunk_corpus
from triage.retrieval.corpus import load_corpus
from triage.retrieval.embeddings import build_embedder
from triage.retrieval.store import SearchResult, build_store


class Retriever:
    """Query the indexed corpus. One instance per triage run."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._embedder = build_embedder(config.retrieval.embedder, config.retrieval.embedding_dim)
        self._store = build_store(config.retrieval.store, database_url=config.env.database_url)

    @property
    def k(self) -> int:
        return self._config.retrieval.k

    @property
    def embedder_name(self) -> str:
        return self._embedder.name

    def rebuild(self, corpus_dir: Path | str | None = None) -> int:
        """Re-chunk and re-embed the whole corpus. Returns the chunk count."""
        documents = load_corpus(corpus_dir or self._config.retrieval.corpus_dir)
        chunks = chunk_corpus(
            documents,
            chunk_tokens=self._config.retrieval.chunk_tokens,
            chunk_overlap=self._config.retrieval.chunk_overlap,
        )
        return self._store.rebuild(chunks, self._embedder)

    def search(self, query: str, k: int | None = None) -> list[SearchResult]:
        return self._store.search(query, self._embedder, k or self.k)

    def count(self) -> int:
        return self._store.count()
