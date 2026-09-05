"""Corpus loading.

Every corpus document carries YAML frontmatter naming where it came from and
under what license. Citations surface that provenance, so a document without
frontmatter is a corpus bug, not a warning to skip past.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
CORPUS_SUFFIXES = {".md", ".yaml", ".yml", ".txt"}

REQUIRED_KEYS = ("title", "source_url", "license")


class CorpusError(ValueError):
    """A corpus document is missing required provenance."""


@dataclass(frozen=True)
class Document:
    """One corpus document: provenance plus body text."""

    doc_id: str
    title: str
    source_url: str
    license: str
    body: str
    path: Path
    tags: tuple[str, ...] = ()

    @property
    def source(self) -> str:
        """What a citation shows: the repo-relative path of the document."""
        return self.doc_id


def parse_document(text: str, *, doc_id: str, path: Path) -> Document:
    """Split frontmatter from body and validate provenance keys."""
    match = FRONTMATTER.match(text)
    if not match:
        raise CorpusError(f"{doc_id}: missing YAML frontmatter")
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise CorpusError(f"{doc_id}: frontmatter is not a mapping")
    missing = [key for key in REQUIRED_KEYS if not meta.get(key)]
    if missing:
        raise CorpusError(f"{doc_id}: frontmatter missing {', '.join(missing)}")
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return Document(
        doc_id=doc_id,
        title=str(meta["title"]),
        source_url=str(meta["source_url"]),
        license=str(meta["license"]),
        body=match.group(2).strip(),
        path=path,
        tags=tuple(str(t) for t in tags),
    )


def load_corpus(root: Path | str) -> list[Document]:
    """Load every corpus document under ``root``, sorted by path for determinism."""
    root_path = Path(root)
    if not root_path.exists():
        raise CorpusError(f"corpus directory not found: {root_path}")
    documents: list[Document] = []
    for path in sorted(root_path.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in CORPUS_SUFFIXES:
            continue
        doc_id = path.relative_to(root_path.parent).as_posix()
        documents.append(parse_document(path.read_text(encoding="utf-8"), doc_id=doc_id, path=path))
    if not documents:
        raise CorpusError(f"no corpus documents found under {root_path}")
    return documents
