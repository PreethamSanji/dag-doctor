"""Card store, feedback write-back, and the dashboard API.

No network and no model: the API is a read layer over artifacts that already
exist, so it can be tested against a temp directory of stored cards.
"""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from triage.card.schema import (
    Citation,
    EvidenceStep,
    IncidentKey,
    RootCause,
    RootCauseCategory,
    RunMetadata,
    TriageCard,
)
from triage.eval.labels import discover_cases, load_label
from triage.metrics import REGISTRY
from triage.server.app import create_app
from triage.server.cards import CardStore
from triage.server.feedback import FeedbackError, record_feedback


def make_card(**overrides) -> TriageCard:
    fields = {
        "incident": IncidentKey(
            dag_id="missing_variable_extract", task_id="extract", run_id="manual__1"
        ),
        "root_cause": RootCause(
            category=RootCauseCategory.CONFIG_ERROR,
            hypothesis="The s3_bucket Variable is unset.",
            confidence=0.86,
        ),
        "suggested_fix": "Define the s3_bucket Airflow Variable.",
        "citations": [
            Citation(
                source="corpus/helm/values.yaml",
                chunk_id="corpus/helm/values.yaml#000",
                quote="AIRFLOW_VAR_S3_BUCKET",
            )
        ],
        "evidence_trail": [
            EvidenceStep(
                step=1, tool="search_logs", args={"pattern": "KeyError"}, result_digest="d"
            )
        ],
        "run": RunMetadata(model="claude-opus-5", steps_used=1, latency_ms=1200, cost_usd=0.08),
    }
    fields.update(overrides)
    return TriageCard(**fields)


@pytest.fixture
def store(tmp_path) -> CardStore:
    return CardStore(tmp_path / "cards")


@pytest.fixture
def client(tmp_path, store):
    app = create_app(
        cards_dir=store.root,
        feedback_dir=tmp_path / "golden",
        report_path=tmp_path / "missing.json",
    )
    return TestClient(app)


def test_store_round_trips_card_and_incident(store, missing_variable_incident):
    card_id = store.save(make_card(), missing_variable_incident)
    stored = store.get(card_id)

    assert stored.card.root_cause.category is RootCauseCategory.CONFIG_ERROR
    # Incident is kept so feedback can become a golden case.
    assert stored.incident.task_instance.dag_id == "missing_variable_extract"


def test_store_lists_newest_first(store, missing_variable_incident):
    first = store.save(make_card(), missing_variable_incident)
    second = store.save(make_card(), missing_variable_incident)

    listed = [stored.card_id for stored in store.list()]
    assert listed[0] == second
    assert first in listed


def test_store_rejects_a_traversing_card_id(store):
    with pytest.raises(KeyError):
        store.get("../../etc/passwd")


def test_summary_carries_no_incident_content(store, missing_variable_incident):
    card_id = store.save(make_card(), missing_variable_incident)
    summary = store.get(card_id).summary()

    assert summary["category"] == "config_error"
    assert "log" not in summary
    assert "KeyError" not in str(summary)


def test_thumbs_up_writes_a_human_labeled_case(store, missing_variable_incident, tmp_path):
    card_id = store.save(make_card(), missing_variable_incident)
    written = record_feedback(store.get(card_id), verdict="up", out_dir=tmp_path / "golden")

    label = load_label(written.label_path)
    assert label.source == "human"
    assert label.root_cause.value == "config_error"
    assert label.expected_citations == ["corpus/helm/values.yaml"]
    assert written.fixture.exists()


def test_thumbs_down_records_the_correction(store, missing_variable_incident, tmp_path):
    card_id = store.save(make_card(), missing_variable_incident)
    written = record_feedback(
        store.get(card_id),
        verdict="down",
        root_cause="code_error",
        expected_fix="Fix the column name in transform",
        notes="the traceback frame is in DAG code",
        out_dir=tmp_path / "golden",
    )

    label = load_label(written.label_path)
    assert label.root_cause.value == "code_error"
    assert label.expected_fix == "Fix the column name in transform"
    # A correction drops citations; they weren't verified as correct.
    assert label.expected_citations == []
    assert label.notes


def test_thumbs_down_must_name_the_right_answer(store, missing_variable_incident, tmp_path):
    card_id = store.save(make_card(), missing_variable_incident)
    with pytest.raises(FeedbackError, match="correct root_cause"):
        record_feedback(store.get(card_id), verdict="down", out_dir=tmp_path / "golden")


def test_feedback_rejects_a_category_outside_the_taxonomy(
    store, missing_variable_incident, tmp_path
):
    card_id = store.save(make_card(), missing_variable_incident)
    with pytest.raises(FeedbackError, match="taxonomy"):
        record_feedback(
            store.get(card_id),
            verdict="down",
            root_cause="operator_was_tired",
            out_dir=tmp_path / "golden",
        )


def test_promoted_feedback_is_discoverable_as_an_eval_case(
    store, missing_variable_incident, tmp_path
):
    """Feedback is data: a thumb becomes a case the harness runs like any other."""
    golden = tmp_path / "golden"
    card_id = store.save(make_card(), missing_variable_incident)
    record_feedback(store.get(card_id), verdict="up", out_dir=golden)

    cases = discover_cases(golden_dir=golden, injection_dir=tmp_path / "none")
    assert len(cases) == 1
    assert cases[0].label.source == "human"


def test_written_label_is_readable_yaml(store, missing_variable_incident, tmp_path):
    card_id = store.save(make_card(), missing_variable_incident)
    written = record_feedback(store.get(card_id), verdict="up", out_dir=tmp_path / "golden")

    raw = yaml.safe_load(written.label_path.read_text(encoding="utf-8"))
    assert raw["root_cause"] == "config_error"
    assert raw["source"] == "human"


def test_api_lists_and_fetches_cards(client, store, missing_variable_incident):
    card_id = store.save(make_card(), missing_variable_incident)

    listed = client.get("/api/cards").json()["cards"]
    assert [card["card_id"] for card in listed] == [card_id]

    detail = client.get(f"/api/cards/{card_id}").json()
    assert detail["card"]["root_cause"]["category"] == "config_error"
    assert detail["card"]["evidence_trail"][0]["tool"] == "search_logs"


def test_api_404s_on_an_unknown_card(client):
    assert client.get("/api/cards/nope").status_code == 404


def test_api_feedback_writes_a_case_and_rejects_a_bare_thumbs_down(
    client, store, missing_variable_incident
):
    card_id = store.save(make_card(), missing_variable_incident)

    ok = client.post(f"/api/cards/{card_id}/feedback", json={"verdict": "up"})
    assert ok.status_code == 200
    assert ok.json()["root_cause"] == "config_error"

    bad = client.post(f"/api/cards/{card_id}/feedback", json={"verdict": "down"})
    assert bad.status_code == 400


def test_api_reports_no_eval_before_the_first_run(client):
    assert client.get("/api/eval/latest").json() == {"available": False}


def test_api_serves_the_taxonomy_and_prometheus_metrics(client):
    health = client.get("/api/health").json()
    assert "config_error" in health["taxonomy"]

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "triage_runs_total" in metrics.text


def test_metrics_record_a_card_without_touching_it():
    from triage.metrics import record_card

    card = make_card(security_flags=["injection_detected"])
    record_card(card)

    assert (
        REGISTRY.get_sample_value(
            "triage_runs_total", {"mode": "agent", "category": "config_error"}
        )
        >= 1
    )
    assert (
        REGISTRY.get_sample_value("triage_security_flags_total", {"flag": "injection_detected"})
        >= 1
    )
    assert (
        REGISTRY.get_sample_value(
            "triage_tool_calls_total", {"tool": "search_logs", "outcome": "ok"}
        )
        >= 1
    )
