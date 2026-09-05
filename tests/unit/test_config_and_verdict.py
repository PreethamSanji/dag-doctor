"""Config loading and verdict parsing."""

from __future__ import annotations

import pytest

from triage.agent.verdict import VerdictParseError, parse_verdict
from triage.config import load_config
from triage.llm import Completion, Usage, price_of

VALID_JSON = (
    '{"root_cause": {"category": "config_error", "hypothesis": "Missing variable.",'
    ' "confidence": 0.8}, "suggested_fix": "Set AIRFLOW_VAR_S3_BUCKET.",'
    ' "citations": [], "insufficient_evidence": false}'
)


def completion(text: str) -> Completion:
    return Completion(content=[{"type": "text", "text": text}], stop_reason="end_turn")


def test_shipped_config_loads_and_is_internally_consistent():
    config = load_config("config/default.yaml")

    assert config.agent.model
    assert config.agent.max_steps > 0
    assert config.agent.mode in {"single_shot", "agent"}
    assert config.retrieval.store in {"memory", "pgvector"}
    assert config.retrieval.k > 0
    assert config.retrieval.chunk_overlap < config.retrieval.chunk_tokens


def test_llm_model_env_var_overrides_config(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-5")

    assert load_config("config/default.yaml").agent.model == "claude-sonnet-5"


def test_fingerprint_records_what_an_eval_must_reproduce():
    fingerprint = load_config("config/default.yaml").fingerprint

    assert set(fingerprint) == {
        "model",
        "effort",
        "max_steps",
        "mode",
        "retrieval_k",
        "embedder",
    }


def test_valid_verdict_parses():
    parsed = parse_verdict(completion(VALID_JSON))

    assert parsed.root_cause.category.value == "config_error"
    assert parsed.suggested_fix.startswith("Set AIRFLOW_VAR")


def test_json_wrapped_in_prose_is_salvaged():
    parsed = parse_verdict(completion(f"Here is the verdict:\n```json\n{VALID_JSON}\n```"))

    assert parsed.root_cause.confidence == 0.8


@pytest.mark.parametrize(
    "text",
    [
        "",
        "I could not determine the root cause.",
        '{"root_cause": {"category": "gremlins", "hypothesis": "h", "confidence": 0.1},'
        ' "suggested_fix": "f"}',
        '{"suggested_fix": "f"}',
    ],
)
def test_unparseable_responses_raise_rather_than_guess(text):
    with pytest.raises(VerdictParseError):
        parse_verdict(completion(text))


def test_pricing_is_per_million_tokens():
    assert price_of("claude-opus-5", 1_000_000, 0) == pytest.approx(5.00)
    assert price_of("claude-opus-5", 0, 1_000_000) == pytest.approx(25.00)


def test_unknown_model_still_costs_something():
    assert price_of("some-future-model", 1_000_000, 0) > 0


def test_usage_accumulates_across_requests():
    usage = Usage()
    usage.add("claude-opus-5", 1000, 500)
    usage.add("claude-opus-5", 1000, 500)

    assert usage.requests == 2
    assert usage.input_tokens == 2000
    assert usage.cost_usd == pytest.approx(price_of("claude-opus-5", 2000, 1000))
