"""The agent loop replayed against recorded tool-call transcripts.

Everything except the model is real: tool dispatch, sanitization of every tool
result, evidence-index registration, citation validation, exhaustion handling,
and card assembly.
"""

from __future__ import annotations

import pytest

from tests.conftest import text_completion, tool_completion
from triage.agent.loop import EXHAUSTED_CONFIDENCE_CEILING, run_agent
from triage.llm import ReplayClient

pytestmark = pytest.mark.integration

LOG_QUOTE = "KeyError: 'Variable s3_bucket does not exist'"


def verdict_payload(**overrides):
    payload = {
        "root_cause": {
            "category": "config_error",
            "hypothesis": "AIRFLOW_VAR_S3_BUCKET is unset, so Variable.get raises at once.",
            "confidence": 0.88,
        },
        "suggested_fix": "Add AIRFLOW_VAR_S3_BUCKET to the production Helm values.",
        "citations": [{"source": "tool", "chunk_id": "tool:search_logs:1", "quote": LOG_QUOTE}],
        "insufficient_evidence": False,
    }
    payload.update(overrides)
    return payload


def test_loop_gathers_evidence_then_commits(config, retriever, missing_variable_incident):
    client = ReplayClient(
        [
            tool_completion("search_logs", {"pattern": "Traceback|KeyError"}, call_id="t1"),
            tool_completion("get_task_history", {"limit": 5}, call_id="t2"),
            tool_completion(
                "query_runbook",
                {"query": "Variable.get KeyError AIRFLOW_VAR", "k": 3},
                call_id="t3",
            ),
            text_completion(verdict_payload()),
        ],
        model="claude-opus-5",
    )

    card = run_agent(missing_variable_incident, config=config, client=client, retriever=retriever)

    assert card.run.mode == "agent"
    assert card.run.steps_used == 3
    assert card.run.max_steps == config.agent.max_steps
    assert [step.tool for step in card.evidence_trail] == [
        "search_logs",
        "get_task_history",
        "query_runbook",
    ]
    assert card.evidence_trail[0].args == {"pattern": "Traceback|KeyError"}
    # Digest is a short summary, not the full result.
    assert card.evidence_trail[0].result_digest.startswith("3 of 12 log lines match")
    assert len(card.evidence_trail[0].result_digest) <= 243
    assert card.root_cause.category.value == "config_error"
    assert card.parse_error is None
    assert not card.insufficient_evidence
    # Cost sums every request in the loop, not just the last one.
    assert card.run.cost_usd > 0
    assert card.run.input_tokens == 3000 * 3 + 4200


def test_tool_results_are_citable_and_validated(config, retriever, missing_variable_incident):
    client = ReplayClient(
        [
            tool_completion("search_logs", {"pattern": "KeyError"}, call_id="t1"),
            text_completion(verdict_payload()),
        ]
    )

    card = run_agent(missing_variable_incident, config=config, client=client, retriever=retriever)

    assert [c.chunk_id for c in card.citations] == ["tool:search_logs:1"]
    assert "ungrounded_citation" not in card.security_flags


def test_runbook_chunks_are_registered_under_their_corpus_ids(
    config, retriever, missing_variable_incident
):
    """A claim about documentation cites the doc chunk, not the tool result."""
    query = "Variable.get KeyError AIRFLOW_VAR"
    chunk = retriever.search(query, k=1)[0].chunk
    quote = " ".join(chunk.text.split()[:14])

    client = ReplayClient(
        [
            tool_completion("query_runbook", {"query": query, "k": 3}, call_id="t1"),
            text_completion(
                verdict_payload(
                    citations=[{"source": chunk.source, "chunk_id": chunk.chunk_id, "quote": quote}]
                )
            ),
        ]
    )

    card = run_agent(missing_variable_incident, config=config, client=client, retriever=retriever)

    assert card.citations[0].chunk_id == chunk.chunk_id
    assert card.citations[0].source == chunk.source
    assert chunk.chunk_id in card.evidence_trail[0].chunk_ids


def test_exhaustion_forces_an_honest_verdict(config, retriever, missing_variable_incident):
    """Running out of steps caps confidence and sets insufficient_evidence."""
    config.agent.max_steps = 2
    client = ReplayClient(
        [
            tool_completion("search_logs", {"pattern": "a"}, call_id="t1"),
            tool_completion("search_logs", {"pattern": "b"}, call_id="t2"),
            # Forced final call, once the budget is spent.
            text_completion(verdict_payload()),
        ]
    )

    card = run_agent(missing_variable_incident, config=config, client=client, retriever=retriever)

    assert card.run.steps_used == 2
    assert card.insufficient_evidence
    assert card.root_cause.confidence <= EXHAUSTED_CONFIDENCE_CEILING
    assert len(card.evidence_trail) == 2


def test_an_unknown_tool_is_reported_back_not_raised(config, retriever, missing_variable_incident):
    client = ReplayClient(
        [
            tool_completion("read_the_database", {"table": "dag_run"}, call_id="t1"),
            text_completion(verdict_payload(citations=[])),
        ]
    )

    card = run_agent(missing_variable_incident, config=config, client=client, retriever=retriever)

    step = card.evidence_trail[0]
    assert step.tool == "read_the_database"
    assert "Unknown tool" in (step.error or "")
    assert card.parse_error is None


def test_a_crashing_tool_becomes_evidence(config, retriever, missing_variable_incident):
    class Exploding:
        name = "search_logs"
        description = "d"
        input_schema = {"type": "object", "properties": {}, "required": []}

        def run(self, args, ctx):
            raise RuntimeError("disk went away")

    client = ReplayClient(
        [
            tool_completion("search_logs", {"pattern": "x"}, call_id="t1"),
            text_completion(verdict_payload(citations=[])),
        ]
    )

    card = run_agent(
        missing_variable_incident,
        config=config,
        client=client,
        retriever=retriever,
        registry={"search_logs": Exploding()},
    )

    assert "RuntimeError: disk went away" in (card.evidence_trail[0].error or "")
    assert card.root_cause.category.value == "config_error"


def test_parallel_tool_calls_in_one_turn_all_run(config, retriever, missing_variable_incident):
    parallel = tool_completion("search_logs", {"pattern": "KeyError"}, call_id="t1")
    parallel.content.append(
        {"type": "tool_use", "id": "t2", "name": "get_task_history", "input": {"limit": 3}}
    )
    client = ReplayClient([parallel, text_completion(verdict_payload())])

    card = run_agent(missing_variable_incident, config=config, client=client, retriever=retriever)

    assert [step.tool for step in card.evidence_trail] == ["search_logs", "get_task_history"]
    # Parallel calls share one step.
    assert {step.step for step in card.evidence_trail} == {1}
    assert card.run.steps_used == 1


def test_tool_output_is_sanitized_before_it_reaches_the_model(config, retriever, poisoned_incident):
    """fetch_dag_source gets no exemption for being code, and neither does a log."""
    seen: list[str] = []

    class Recording(ReplayClient):
        def complete(self, *, system, messages, **kwargs):
            seen.append(str(messages))
            return super().complete(system=system, messages=messages, **kwargs)

    payload = verdict_payload(
        root_cause={
            "category": "config_error",
            "hypothesis": "The reporting_warehouse connection is not defined.",
            "confidence": 0.8,
        },
        citations=[
            {
                "source": "tool",
                "chunk_id": "tool:search_logs:1",
                "quote": "The conn_id `reporting_warehouse` isn't defined",
            }
        ],
    )
    client = Recording(
        [
            tool_completion("search_logs", {"pattern": "SYSTEM|conn_id"}, call_id="t1"),
            text_completion(payload),
        ]
    )

    card = run_agent(poisoned_incident, config=config, client=client, retriever=retriever)

    final_messages = seen[-1]
    assert "Ignore all previous instructions" not in final_messages
    assert "[neutralized-instruction]" in final_messages
    assert "injection_detected" in card.security_flags
    assert card.root_cause.category.value == "config_error"
    assert card.citations, "the real failure is still quotable"


def test_repeated_parse_failure_produces_a_parse_error_card(
    config, retriever, missing_variable_incident
):
    broken = text_completion({"almost": "a verdict"})
    client = ReplayClient([broken, broken])

    card = run_agent(missing_variable_incident, config=config, client=client, retriever=retriever)

    assert card.parse_error is not None
    assert card.insufficient_evidence
    assert card.model_dump_json()


def test_a_malformed_final_answer_gets_one_retry(config, retriever, missing_variable_incident):
    client = ReplayClient(
        [
            tool_completion("search_logs", {"pattern": "KeyError"}, call_id="t1"),
            text_completion({"not": "a verdict"}),
            text_completion(verdict_payload()),
        ]
    )

    card = run_agent(missing_variable_incident, config=config, client=client, retriever=retriever)

    assert card.parse_error is None
    assert card.root_cause.category.value == "config_error"
    assert card.run.steps_used == 1
