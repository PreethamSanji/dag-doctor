"""The tool registry.

Six tools, each a distinct kind of evidence. The set is deliberately small: a
tool the eval set does not measure is a tool that does not belong here.
"""

from __future__ import annotations

from triage.agent.tools.base import (
    Tool,
    ToolContext,
    ToolOutput,
    digest,
    schema,
    spec,
)
from triage.agent.tools.check_recent_deploys import CheckRecentDeploys
from triage.agent.tools.fetch_dag_source import FetchDagSource
from triage.agent.tools.get_prometheus_metric import GetPrometheusMetric
from triage.agent.tools.get_task_history import GetTaskHistory
from triage.agent.tools.query_runbook import QueryRunbook
from triage.agent.tools.search_logs import SearchLogs


def default_registry() -> dict[str, Tool]:
    """Every tool the agent may call, keyed by name."""
    tools: list[Tool] = [
        SearchLogs(),
        GetTaskHistory(),
        FetchDagSource(),
        QueryRunbook(),
        CheckRecentDeploys(),
        GetPrometheusMetric(),
    ]
    return {tool.name: tool for tool in tools}


def tool_specs(registry: dict[str, Tool]) -> list[dict]:
    """Tool definitions in the order the model sees them."""
    return [spec(tool) for tool in registry.values()]


__all__ = [
    "CheckRecentDeploys",
    "FetchDagSource",
    "GetPrometheusMetric",
    "GetTaskHistory",
    "QueryRunbook",
    "SearchLogs",
    "Tool",
    "ToolContext",
    "ToolOutput",
    "default_registry",
    "digest",
    "schema",
    "spec",
    "tool_specs",
]
