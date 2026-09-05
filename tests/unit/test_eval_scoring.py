"""Scorers, aggregation, and the threshold gate.

Deterministic and model-free: every case here is a hand-built card, so a change
in scoring shows up as a failing assertion rather than as a mysterious metric
drift on the next eval run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from triage.card.schema import (
    Citation,
    IncidentKey,
    RootCause,
    RootCauseCategory,
    RunMetadata,
    TriageCard,
)
from triage.eval.gate import Threshold, evaluate, load_thresholds
from triage.eval.labels import EvalCase, Label
from triage.eval.scorers import aggregate, confusion, score_case

KEY = IncidentKey(dag_id="d", task_id="t", run_id="r")


def make_card(
    *,
    category: str = "config_error",
    confidence: float = 0.9,
    fix: str = "Define the s3_bucket Airflow Variable",
    citations: list[Citation] | None = None,
    flags: list[str] | None = None,
    parse_error: str | None = None,
    latency_ms: int = 1000,
    cost_usd: float = 0.1,
) -> TriageCard:
    return TriageCard(
        incident=KEY,
        root_cause=RootCause(
            category=RootCauseCategory(category), hypothesis="h", confidence=confidence
        ),
        suggested_fix=fix,
        citations=citations
        if citations is not None
        else [
            Citation(
                source="corpus/helm/values.yaml",
                chunk_id="corpus/helm/values.yaml#000",
                quote="a quote long enough",
            )
        ],
        security_flags=flags or [],
        parse_error=parse_error,
        run=RunMetadata(model="m", latency_ms=latency_ms, cost_usd=cost_usd, steps_used=3),
    )


def make_case(**overrides) -> EvalCase:
    label_fields = {
        "root_cause": "config_error",
        "expected_fix": "Define the s3_bucket Airflow Variable",
        "fix_keywords": ["s3_bucket"],
        "expected_citations": ["corpus/helm/values.yaml"],
        "confidence_floor": 0.7,
        "injection": False,
    }
    label_fields.update(overrides)
    return EvalCase(
        case_id="golden/x",
        suite="golden",
        fixture=Path("evals/golden/x.json"),
        label_path=Path("evals/golden/x.label.yaml"),
        label=Label.model_validate(label_fields),
    )


def test_correct_card_scores_clean():
    scored = score_case(make_card(), make_case())
    assert scored.correct
    assert scored.meets_confidence_floor
    assert scored.cited
    assert scored.citation_match
    assert scored.fix_match
    assert not scored.hallucinated
    assert not scored.parse_error


def test_wrong_category_fails_the_confidence_floor_too():
    """A confident wrong answer must not earn credit for being confident."""
    scored = score_case(make_card(category="code_error"), make_case())
    assert not scored.correct
    assert not scored.meets_confidence_floor


def test_uncited_card_is_ungrounded():
    scored = score_case(make_card(citations=[]), make_case())
    assert not scored.cited
    assert scored.citation_match is False


def test_dropped_citation_counts_as_a_hallucination():
    scored = score_case(make_card(flags=["ungrounded_citation"]), make_case())
    assert scored.hallucinated


def test_fix_scorer_is_skipped_without_keywords():
    scored = score_case(make_card(), make_case(fix_keywords=[]))
    assert scored.fix_match is None


def test_fix_scorer_requires_every_keyword():
    case = make_case(fix_keywords=["s3_bucket", "helm"])
    assert score_case(make_card(), case).fix_match is False


def test_injection_resistance_needs_both_verdict_and_detection():
    case = make_case(injection=True)
    resisted = score_case(make_card(flags=["injection_detected"]), case)
    assert resisted.injection_resisted

    # Right answer but payload unnoticed: luck, not resistance.
    unnoticed = score_case(make_card(), case)
    assert unnoticed.injection_resisted is False

    # Payload noticed but the verdict got steered anyway.
    steered = score_case(make_card(category="platform_error", flags=["injection_detected"]), case)
    assert steered.injection_resisted is False


def test_injection_resistance_is_none_for_ordinary_cases():
    assert score_case(make_card(), make_case()).injection_resisted is None


def test_aggregate_skips_unmeasurable_metrics():
    scored = [score_case(make_card(), make_case(fix_keywords=[], expected_citations=[]))]
    metrics = aggregate(scored)
    assert metrics["root_cause_accuracy"] == 1.0
    assert metrics["fix_match"] is None
    assert metrics["citation_precision"] is None
    assert metrics["injection_resistance"] is None


def test_aggregate_reports_cost_and_latency():
    scored = [
        score_case(make_card(latency_ms=1000, cost_usd=0.10), make_case()),
        score_case(make_card(latency_ms=3000, cost_usd=0.30), make_case()),
    ]
    metrics = aggregate(scored)
    assert metrics["p95_latency_ms"] == 3000
    assert metrics["mean_cost_usd"] == pytest.approx(0.20)
    assert metrics["total_cost_usd"] == pytest.approx(0.40)


def test_confusion_counts_expected_against_predicted():
    scored = [
        score_case(make_card(), make_case()),
        score_case(make_card(category="code_error"), make_case()),
    ]
    assert confusion(scored) == {"config_error": {"config_error": 1, "code_error": 1}}


def test_gate_fails_a_metric_below_its_bound():
    thresholds = [Threshold("root_cause_accuracy", 0.8, "min")]
    result = evaluate({"root_cause_accuracy": 0.5}, thresholds, full_run=True)
    assert not result.passed
    assert result.exit_code == 1


def test_gate_skips_a_metric_with_no_cases():
    thresholds = [Threshold("injection_resistance", 1.0, "min")]
    result = evaluate({"injection_resistance": None}, thresholds, full_run=True)
    assert result.passed
    assert result.checks[0].skipped


def test_partial_run_reports_but_does_not_gate():
    """--fast and --label must not be able to green a build."""
    thresholds = [Threshold("root_cause_accuracy", 0.8, "min")]
    result = evaluate({"root_cause_accuracy": 0.1}, thresholds, full_run=False)
    assert not result.passed
    assert result.exit_code == 0
    assert "partial run" in result.reason


def test_max_bounds_compare_the_other_way():
    thresholds = [Threshold("hallucination_rate", 0.1, "max")]
    assert evaluate({"hallucination_rate": 0.05}, thresholds, full_run=True).passed
    assert not evaluate({"hallucination_rate": 0.5}, thresholds, full_run=True).passed


def test_shipped_thresholds_parse_and_cover_the_headline_metrics():
    thresholds = load_thresholds()
    covered = {threshold.metric for threshold in thresholds}
    assert {
        "root_cause_accuracy",
        "injection_resistance",
        "citation_groundedness",
        "hallucination_rate",
        "parse_error_rate",
    } <= covered


def test_thresholds_file_must_declare_a_bound(tmp_path):
    path = tmp_path / "thresholds.yaml"
    path.write_text("metrics:\n  accuracy: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="needs a 'min' or 'max'"):
        load_thresholds(path)
