"""Tool behaviour. No network, no LLM - tools operate on the ingested incident."""

from __future__ import annotations

import pytest

from triage.agent.tools import default_registry, tool_specs
from triage.agent.tools.base import ToolContext


@pytest.fixture
def ctx(missing_variable_incident, config, retriever) -> ToolContext:
    return ToolContext(incident=missing_variable_incident, config=config, retriever=retriever)


@pytest.fixture
def tools():
    return default_registry()


def test_the_registry_is_the_six_documented_tools(tools):
    assert set(tools) == {
        "search_logs",
        "get_task_history",
        "fetch_dag_source",
        "query_runbook",
        "check_recent_deploys",
        "get_prometheus_metric",
    }


def test_every_tool_spec_is_strict_and_documented(tools):
    for spec in tool_specs(tools):
        assert spec["description"].strip()
        schema = spec["input_schema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) <= set(schema["properties"])
        for prop in schema["properties"].values():
            assert prop.get("description"), spec["name"]


def test_search_logs_finds_the_raising_frame(tools, ctx):
    output = tools["search_logs"].run({"pattern": "KeyError", "context_lines": 1}, ctx)

    assert not output.failed
    assert "Variable s3_bucket does not exist" in output.content
    assert output.content.startswith("2 of")


def test_search_logs_reports_a_miss_as_a_finding(tools, ctx):
    output = tools["search_logs"].run({"pattern": "SIGKILL"}, ctx)

    assert not output.failed
    assert "0 lines" in output.content
    assert "does not contain this signature" in output.content


def test_search_logs_rejects_a_bad_regex_without_raising(tools, ctx):
    output = tools["search_logs"].run({"pattern": "(unclosed"}, ctx)

    assert output.failed
    assert "invalid regular expression" in output.content


def test_get_task_history_summarises_success_and_failure(tools, ctx):
    output = tools["get_task_history"].run({"limit": 5}, ctx)

    assert "2 success" in output.content
    assert "scheduled__2025-05-18T06:00:00+00:00" in output.content


def test_get_task_history_says_so_when_there_is_none(tools, config, poisoned_incident):
    output = tools["get_task_history"].run(
        {}, ToolContext(incident=poisoned_incident, config=config)
    )

    assert "No prior runs recorded" in output.content


def test_fetch_dag_source_returns_numbered_lines(tools, ctx):
    output = tools["fetch_dag_source"].run({}, ctx)

    assert "missing_variable_extract.py" in output.content
    assert "1: from airflow.decorators import dag, task" in output.content


def test_fetch_dag_source_search_narrows_to_the_hit(tools, ctx):
    output = tools["fetch_dag_source"].run({"search": "Variable.get", "context_lines": 1}, ctx)

    assert "1 lines contain 'Variable.get'" in output.content
    assert ">" in output.content


def test_fetch_dag_source_missing_is_a_finding_not_a_crash(tools, config, poisoned_incident):
    output = tools["fetch_dag_source"].run(
        {}, ToolContext(incident=poisoned_incident, config=config)
    )

    assert output.failed
    assert "lower confidence" in output.content


def test_query_runbook_returns_chunks_with_ids(tools, ctx):
    output = tools["query_runbook"].run(
        {"query": "Variable.get KeyError AIRFLOW_VAR missing", "k": 3}, ctx
    )

    assert not output.failed
    assert output.content.count("[chunk_id=") == 3
    # Chunks are staged here for the loop to register by id.
    assert len(ctx.extras["retrieved_chunks"]) == 3


def test_query_runbook_without_an_index_refuses_to_invent(tools, config, missing_variable_incident):
    output = tools["query_runbook"].run(
        {"query": "anything"},
        ToolContext(incident=missing_variable_incident, config=config, retriever=None),
    )

    assert output.failed
    assert "ungrounded" in output.content


def test_check_recent_deploys_reports_the_time_delta(tools, ctx):
    output = tools["check_recent_deploys"].run({}, ctx)

    assert "3f9a1c22bd41" in output.content
    assert "h before failure" in output.content


def test_check_recent_deploys_absence_is_not_evidence(tools, config, poisoned_incident):
    output = tools["check_recent_deploys"].run(
        {}, ToolContext(incident=poisoned_incident, config=config)
    )

    assert "do not treat this as evidence" in output.content


def test_prometheus_without_a_backend_says_so(tools, ctx, monkeypatch):
    monkeypatch.delenv("PROMETHEUS_BASE_URL", raising=False)

    output = tools["get_prometheus_metric"].run({"query": "up"}, ctx)

    assert output.failed
    assert "No metrics backend is configured" in output.content
    assert "reduced confidence" in output.content
