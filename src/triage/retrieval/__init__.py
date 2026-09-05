"""Chunking, embeddings, and the vector store behind retrieval."""

from triage.retrieval.chunking import Chunk, chunk_corpus, chunk_document
from triage.retrieval.corpus import CorpusError, Document, load_corpus, parse_document
from triage.retrieval.embeddings import Embedder, HashingEmbedder, build_embedder, cosine
from triage.retrieval.retriever import Retriever
from triage.retrieval.store import MemoryStore, SearchResult, VectorStore, build_store

__all__ = [
    "Chunk",
    "CorpusError",
    "Document",
    "Embedder",
    "HashingEmbedder",
    "MemoryStore",
    "Retriever",
    "SearchResult",
    "VectorStore",
    "build_embedder",
    "build_store",
    "chunk_corpus",
    "chunk_document",
    "cosine",
    "load_corpus",
    "parse_document",
]
