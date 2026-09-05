"""Citation validation: citations are validated, not decorated.

Every citation on a card must resolve to a chunk that was actually in model
context during *this* run - a retrieved corpus chunk or a tool result recorded
in the evidence trail - and its quote must appear in that chunk's text.

Anything that fails resolution is dropped from the card and reported, because a
plausible-looking citation to a chunk we never retrieved is exactly the
hallucination the eval harness is meant to catch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from triage.card.schema import Citation

_WS = re.compile(r"\s+")
#: Quotes shorter than this can't be verified.
MIN_QUOTE_CHARS = 12


def normalize(text: str) -> str:
    """Whitespace- and case-insensitive form used for substring matching."""
    return _WS.sub(" ", text).strip().casefold()


@dataclass
class EvidenceIndex:
    """Everything that was in context this run, keyed by chunk id."""

    chunks: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    _normalized: dict[str, str] = field(default_factory=dict, repr=False)

    def add(self, chunk_id: str, text: str, source: str) -> None:
        self.chunks[chunk_id] = text
        self.sources[chunk_id] = source
        self._normalized[chunk_id] = normalize(text)

    def __contains__(self, chunk_id: object) -> bool:
        return chunk_id in self.chunks

    def __len__(self) -> int:
        return len(self.chunks)

    def contains_quote(self, chunk_id: str, quote: str) -> bool:
        haystack = self._normalized.get(chunk_id)
        if haystack is None:
            return False
        return normalize(quote) in haystack

    def find_chunk_for_quote(self, quote: str) -> str | None:
        """Locate a chunk containing this quote, for repairing a wrong chunk_id."""
        needle = normalize(quote)
        for chunk_id, haystack in self._normalized.items():
            if needle in haystack:
                return chunk_id
        return None


@dataclass
class DroppedCitation:
    citation: Citation
    reason: str


@dataclass
class ValidationResult:
    kept: list[Citation]
    dropped: list[DroppedCitation]

    @property
    def groundedness(self) -> float:
        """Share of proposed citations that resolved. 1.0 when none were proposed."""
        total = len(self.kept) + len(self.dropped)
        if total == 0:
            return 1.0
        return len(self.kept) / total

    @property
    def flags(self) -> list[str]:
        return ["ungrounded_citation"] if self.dropped else []


def validate_citations(
    citations: list[Citation],
    index: EvidenceIndex,
    *,
    repair_chunk_id: bool = True,
) -> ValidationResult:
    """Resolve each citation against the run's evidence.

    A citation survives when its ``chunk_id`` is known and its ``quote`` appears
    in that chunk. When ``repair_chunk_id`` is set, a correct quote attached to
    the wrong chunk id is repaired rather than dropped - the evidence is real,
    only the label was wrong - and the citation's ``source`` is rewritten from
    the index so provenance always comes from us, never from the model.

    Args:
        citations: citations proposed by the model.
        index: chunks that were in context this run.
        repair_chunk_id: re-point a verifiable quote at the chunk that holds it.

    Returns:
        A :class:`ValidationResult` with the surviving citations and the reason
        each dropped citation failed.
    """
    kept: list[Citation] = []
    dropped: list[DroppedCitation] = []
    seen: set[tuple[str, str]] = set()

    for citation in citations:
        quote = citation.quote.strip()
        if len(quote) < MIN_QUOTE_CHARS:
            dropped.append(DroppedCitation(citation, "quote_too_short"))
            continue

        chunk_id = citation.chunk_id
        if chunk_id in index and index.contains_quote(chunk_id, quote):
            resolved = chunk_id
        elif repair_chunk_id and (found := index.find_chunk_for_quote(quote)):
            resolved = found
        elif chunk_id not in index:
            dropped.append(DroppedCitation(citation, "unknown_chunk_id"))
            continue
        else:
            dropped.append(DroppedCitation(citation, "quote_not_in_chunk"))
            continue

        key = (resolved, normalize(quote))
        if key in seen:
            continue
        seen.add(key)
        kept.append(
            Citation(
                source=index.sources.get(resolved, citation.source),
                chunk_id=resolved,
                quote=quote,
            )
        )

    return ValidationResult(kept=kept, dropped=dropped)
