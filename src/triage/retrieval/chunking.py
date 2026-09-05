"""Chunking.

Markdown-aware, deterministic, and stable across runs: a chunk id must mean the
same span tomorrow as it did today, or every citation stored in an eval report
silently rots. Ids are ``{doc_id}#{ordinal:03d}`` - ordinal, not a content hash,
so a chunk keeps its identity when a typo upstream is fixed.
"""

from __future__ import annotations

from dataclasses import dataclass

from triage.retrieval.corpus import Document

#: Rough words-per-token ratio. We chunk on words to avoid a network-bound tokenizer.
WORDS_PER_TOKEN = 0.75


@dataclass(frozen=True)
class Chunk:
    """A retrievable span with the provenance a citation needs."""

    chunk_id: str
    doc_id: str
    text: str
    source: str
    source_url: str
    license: str
    title: str
    ordinal: int

    @property
    def header(self) -> str:
        """One-line provenance banner prefixed to the chunk in model context."""
        return f"{self.source} ({self.title}) <{self.source_url}> [{self.license}]"


def _split_sections(body: str) -> list[str]:
    """Split on markdown headings so a chunk rarely straddles two topics."""
    sections: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        if line.startswith("#") and current:
            sections.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    return [section for section in sections if section]


def _window(words: list[str], size: int, overlap: int) -> list[list[str]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    if len(words) <= size:
        return [words]
    stride = max(1, size - overlap)
    windows: list[list[str]] = []
    start = 0
    while start < len(words):
        windows.append(words[start : start + size])
        if start + size >= len(words):
            break
        start += stride
    return windows


def chunk_document(
    document: Document,
    *,
    chunk_tokens: int = 320,
    chunk_overlap: int = 60,
) -> list[Chunk]:
    """Split one document into overlapping, provenance-carrying chunks."""
    size = max(1, int(chunk_tokens * WORDS_PER_TOKEN))
    overlap = max(0, min(int(chunk_overlap * WORDS_PER_TOKEN), size - 1))

    chunks: list[Chunk] = []
    ordinal = 0
    for section in _split_sections(document.body):
        words = section.split()
        if not words:
            continue
        for window in _window(words, size, overlap):
            chunks.append(
                Chunk(
                    chunk_id=f"{document.doc_id}#{ordinal:03d}",
                    doc_id=document.doc_id,
                    text=" ".join(window),
                    source=document.source,
                    source_url=document.source_url,
                    license=document.license,
                    title=document.title,
                    ordinal=ordinal,
                )
            )
            ordinal += 1
    return chunks


def chunk_corpus(
    documents: list[Document],
    *,
    chunk_tokens: int = 320,
    chunk_overlap: int = 60,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for document in documents:
        chunks.extend(
            chunk_document(document, chunk_tokens=chunk_tokens, chunk_overlap=chunk_overlap)
        )
    return chunks
