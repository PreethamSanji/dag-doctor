"""Single-shot triage replayed against recorded model responses.

No network, no API key, no LLM. What is exercised for real: retrieval,
sanitization, prompt assembly, structured-output parsing, citation validation,
and card assembly.
"""

from __future__ import annotations

import pytest

from tests.conftest import text_completion
from triage.agent.single_shot import run_single_shot
from triage.llm import ReplayClient

pytestmark = pytest.mark.integration

CORPUS_QUOTE = "A missing entry raises AirflowNotFoundException at task runtime"
LOG_QUOTE = "KeyError: 'Variable s3_bucket does not exist'"


def verdict_payload(**overrides):
    payload = {
        "root_cause": {
            "category": "config_error",
            "hypothesis": ("AIRFLOW_VAR_S3_BUCKET is absent, so Variable.get raises immediately."),
            "confidence": 0.86,
        },
        "suggested_fix": "Add AIRFLOW_VAR_S3_BUCKET to the production Helm values.",
        "citations": [{"source": "airflow:log", "chunk_id": "incident:log", "quote": LOG_QUOTE}],
        "insufficient_evidence": False,
    }
    payload.update(overrides)
    return payload


def test_happy_path_produces_a_grounded_card(config, retriever, missing_variable_incident):
    client = ReplayClient([text_completion(verdict_payload())], model="claude-opus-5")

    card = run_single_shot(
        missing_variable_incident, config=config, client=client, retriever=retriever
    )

    assert card.root_cause.category.value == "config_error"
    assert card.parse_error is None
    assert [c.chunk_id for c in card.citations] == ["incident:log"]
    assert card.run.mode == "single_shot"
    assert card.run.cost_usd > 0
    assert card.run.input_tokens == 4200
    assert card.run.config_fingerprint["model"] == config.agent.model


def test_hallucinated_citation_is_dropped_and_flagged(config, retriever, missing_variable_incident):
    payload = verdict_payload(
        citations=[
            {"source": "airflow:log", "chunk_id": "incident:log", "quote": LOG_QUOTE},
            {
                "source": "corpus/runbooks/never-existed.md",
                "chunk_id": "corpus/runbooks/never-existed.md#000",
                "quote": "restart the scheduler to clear the variable cache",
            },
        ]
    )
    client = ReplayClient([text_completion(payload)])

    card = run_single_shot(
        missing_variable_incident, config=config, client=client, retriever=retriever
    )

    assert [c.chunk_id for c in card.citations] == ["incident:log"]
    assert "ungrounded_citation" in card.security_flags


def test_malformed_response_gets_one_retry_then_succeeds(
    config, retriever, missing_variable_incident
):
    client = ReplayClient(
        [
            text_completion({"root_cause": {"category": "not-a-category"}}),
            text_completion(verdict_payload()),
        ]
    )

    card = run_single_shot(
        missing_variable_incident, config=config, client=client, retriever=retriever
    )

    assert card.parse_error is None
    assert card.root_cause.category.value == "config_error"
    # Both requests count toward the bill.
    assert card.run.input_tokens == 8400


def test_repeated_parse_failure_becomes_a_parse_error_card(
    config, retriever, missing_variable_incident
):
    broken = text_completion({"nope": True})
    client = ReplayClient([broken, broken])

    card = run_single_shot(
        missing_variable_incident, config=config, client=client, retriever=retriever
    )

    assert card.parse_error is not None
    assert card.insufficient_evidence
    assert card.root_cause.confidence == 0.0
    # A parse failure is a metric, not a crash — the card still validates.
    assert card.model_dump_json()


def test_injection_in_the_log_is_flagged_and_neutralized_before_the_model_sees_it(
    config, retriever, poisoned_incident, monkeypatch
):
    seen: dict[str, str] = {}

    class Recording(ReplayClient):
        def complete(self, *, system, messages, **kwargs):
            seen["system"] = system
            seen["user"] = messages[0]["content"]
            return super().complete(system=system, messages=messages, **kwargs)

    payload = verdict_payload(
        root_cause={
            "category": "config_error",
            "hypothesis": "The reporting_warehouse connection is not defined.",
            "confidence": 0.8,
        },
        citations=[
            {
                "source": "airflow:log",
                "chunk_id": "incident:log",
                "quote": "The conn_id `reporting_warehouse` isn't defined",
            }
        ],
    )
    client = Recording([text_completion(payload)])

    card = run_single_shot(poisoned_incident, config=config, client=client, retriever=retriever)

    assert "injection_detected" in card.security_flags
    assert "Ignore all previous instructions" not in seen["user"]
    assert "[neutralized-instruction]" in seen["user"]
    # Real failure is still visible to the model.
    assert "reporting_warehouse" in seen["user"]
    # State comes from Airflow metadata, outside any untrusted block.
    assert "state: failed" in seen["user"]
    assert card.root_cause.category.value == "config_error"


def test_retrieved_corpus_chunks_are_citable(config, retriever, missing_variable_incident):
    """The model can cite retrieved documentation, and it validates."""
    results = retriever.search("Variable.get KeyError AIRFLOW_VAR missing", k=6)
    chunk = results[0].chunk
    quote = " ".join(chunk.text.split()[:12])

    payload = verdict_payload(
        citations=[{"source": chunk.source, "chunk_id": chunk.chunk_id, "quote": quote}]
    )
    client = ReplayClient([text_completion(payload)])

    card = run_single_shot(
        missing_variable_incident, config=config, client=client, retriever=retriever
    )

    assert card.citations[0].chunk_id == chunk.chunk_id
    assert card.citations[0].source == chunk.source
