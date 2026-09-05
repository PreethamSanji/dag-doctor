"""Citation validation: a citation that does not resolve must not survive."""

from __future__ import annotations

from triage.card.citations import EvidenceIndex, validate_citations
from triage.card.schema import Citation

CHUNK_TEXT = (
    "Variables can be supplied through AIRFLOW_VAR_S3_BUCKET, which backs "
    'Variable.get("s3_bucket"). A missing entry raises KeyError at task runtime.'
)


def index() -> EvidenceIndex:
    evidence = EvidenceIndex()
    evidence.add("corpus/helm/values.yaml#001", CHUNK_TEXT, "corpus/helm/values.yaml")
    evidence.add("incident:log", "KeyError: 'Variable s3_bucket does not exist'", "airflow:log")
    return evidence


def test_valid_citation_survives_and_gets_provenance_from_us():
    citation = Citation(
        source="whatever-the-model-said",
        chunk_id="corpus/helm/values.yaml#001",
        quote="A missing entry raises KeyError at task runtime",
    )

    result = validate_citations([citation], index())

    assert result.dropped == []
    assert result.groundedness == 1.0
    # Source is taken from the index, never trusted from the model.
    assert result.kept[0].source == "corpus/helm/values.yaml"


def test_unknown_chunk_id_is_dropped():
    citation = Citation(
        source="corpus/invented.md",
        chunk_id="corpus/invented.md#000",
        quote="this chunk was never retrieved in this run",
    )

    result = validate_citations([citation], index())

    assert result.kept == []
    assert result.dropped[0].reason == "unknown_chunk_id"
    assert result.flags == ["ungrounded_citation"]
    assert result.groundedness == 0.0


def test_quote_not_present_in_a_real_chunk_is_dropped():
    citation = Citation(
        source="corpus/helm/values.yaml",
        chunk_id="corpus/helm/values.yaml#001",
        quote="the scheduler ran out of database connections",
    )

    result = validate_citations([citation], index())

    assert result.kept == []
    assert result.dropped[0].reason == "quote_not_in_chunk"


def test_wrong_chunk_id_with_a_real_quote_is_repaired():
    """The evidence is real; only the label was wrong."""
    citation = Citation(
        source="corpus/helm/values.yaml",
        chunk_id="incident:log",
        quote="A missing entry raises KeyError at task runtime",
    )

    result = validate_citations([citation], index())

    assert result.kept[0].chunk_id == "corpus/helm/values.yaml#001"
    assert result.dropped == []


def test_repair_can_be_disabled():
    citation = Citation(
        source="corpus/helm/values.yaml",
        chunk_id="incident:log",
        quote="A missing entry raises KeyError at task runtime",
    )

    result = validate_citations([citation], index(), repair_chunk_id=False)

    assert result.kept == []
    assert result.dropped[0].reason == "quote_not_in_chunk"


def test_trivial_quotes_are_rejected():
    citation = Citation(source="s", chunk_id="incident:log", quote="KeyError")

    result = validate_citations([citation], index())

    assert result.dropped[0].reason == "quote_too_short"


def test_whitespace_and_case_differences_still_match():
    citation = Citation(
        source="s",
        chunk_id="corpus/helm/values.yaml#001",
        quote="a  MISSING   entry\nraises KeyError",
    )

    result = validate_citations([citation], index())

    assert len(result.kept) == 1


def test_duplicate_citations_collapse():
    citation = Citation(
        source="s",
        chunk_id="corpus/helm/values.yaml#001",
        quote="A missing entry raises KeyError at task runtime",
    )

    result = validate_citations([citation, citation], index())

    assert len(result.kept) == 1


def test_no_citations_is_perfectly_grounded_but_uncited():
    result = validate_citations([], index())

    assert result.groundedness == 1.0
    assert result.kept == []
