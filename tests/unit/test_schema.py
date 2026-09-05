"""Card schema: structured output or fail loudly."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from triage.card.schema import (
    TAXONOMY,
    Citation,
    IncidentKey,
    RootCause,
    RootCauseCategory,
    RunMetadata,
    TriageCard,
    TriageVerdict,
    verdict_json_schema,
)


def key() -> IncidentKey:
    return IncidentKey(dag_id="d", task_id="t", run_id="r", try_number=2)


def run() -> RunMetadata:
    return RunMetadata(model="claude-opus-5", mode="single_shot", max_steps=8)


def verdict(**overrides) -> TriageVerdict:
    payload = {
        "root_cause": {
            "category": "config_error",
            "hypothesis": "AIRFLOW_VAR_S3_BUCKET is not set.",
            "confidence": 0.82,
        },
        "suggested_fix": "Add AIRFLOW_VAR_S3_BUCKET to the environment.",
        "citations": [],
        "insufficient_evidence": False,
    }
    payload.update(overrides)
    return TriageVerdict.model_validate(payload)


def test_taxonomy_is_closed_and_has_seven_members():
    assert len(TAXONOMY) == 7
    assert set(TAXONOMY) == {c.value for c in RootCauseCategory}


def test_category_outside_the_taxonomy_is_rejected():
    with pytest.raises(ValidationError):
        verdict(
            root_cause={
                "category": "networking",
                "hypothesis": "h",
                "confidence": 0.5,
            }
        )


def test_confidence_is_bounded():
    with pytest.raises(ValidationError):
        RootCause(category=RootCauseCategory.CODE_ERROR, hypothesis="h", confidence=1.4)


def test_unknown_fields_are_rejected():
    """Extra keys mean the model invented structure; that is a parse failure."""
    with pytest.raises(ValidationError):
        verdict(severity="sev1")


def test_incident_key_renders_stably():
    assert str(key()) == "d/t/r#2"


def test_card_from_verdict_carries_server_side_fields():
    card = TriageCard.from_verdict(
        verdict(),
        incident=key(),
        evidence_trail=[],
        security_flags=["injection_detected"],
        run=run(),
    )

    assert card.incident.dag_id == "d"
    assert card.security_flags == ["injection_detected"]
    assert card.root_cause.category is RootCauseCategory.CONFIG_ERROR


def test_parse_error_card_is_still_a_valid_card():
    card = TriageCard.parse_error_card(
        incident=key(),
        error="response was not JSON",
        evidence_trail=[],
        security_flags=[],
        run=run(),
    )

    assert card.parse_error.startswith("response was not JSON")
    assert card.insufficient_evidence
    assert card.root_cause.confidence == 0.0
    # Round-trips cleanly so eval can score it instead of crashing.
    assert TriageCard.model_validate_json(card.model_dump_json()) == card


def test_citations_are_capped():
    many = [
        Citation(source="s", chunk_id=f"c#{i}", quote="a quote long enough to pass")
        for i in range(30)
    ]

    assert len(verdict(citations=[c.model_dump() for c in many]).citations) == 12


def test_verdict_json_schema_is_strict_everywhere():
    schema = verdict_json_schema()

    def assert_strict(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                assert_strict(value)
        elif isinstance(node, list):
            for item in node:
                assert_strict(item)

    assert_strict(schema)
    assert json.dumps(schema)  # serializable as-is for output_config.format
