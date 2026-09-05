"""get_prometheus_metric - the resource evidence a log cannot carry.

A SIGKILL leaves no traceback, so memory and slot pressure have to come from
somewhere other than the task log. This queries Prometheus when one is
configured (``PROMETHEUS_BASE_URL``), and reports its own absence otherwise -
"there is no metric backend here" is a legitimate result, and the agent should
lower confidence rather than guess at numbers.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from triage.agent.tools.base import ToolContext, ToolOutput, schema

MAX_SERIES = 10


class GetPrometheusMetric:
    name = "get_prometheus_metric"
    description = (
        "Evaluate a PromQL query against the metrics backend and return the "
        "resulting series. Use it for evidence the task log cannot contain: "
        "container memory against its limit before an unexplained kill, pool slot "
        "saturation behind a queued task, scheduler heartbeat gaps. If no metrics "
        "backend is configured the tool says so - treat that as missing evidence, "
        "not as a normal reading."
    )
    input_schema: dict[str, Any] = schema(
        {
            "query": {
                "type": "string",
                "description": (
                    "PromQL. Examples: "
                    "'container_memory_max_usage_bytes{pod=~\"airflow-worker.*\"}', "
                    "'airflow_pool_running_slots{pool=\"default_pool\"}'."
                ),
            },
            "lookback_minutes": {
                "type": "integer",
                "description": "Evaluate the query this many minutes before the failure (0-1440).",
            },
        },
        required=["query"],
    )

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        source = "tool:get_prometheus_metric"
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolOutput.failure("query is required", source=source)

        base_url = os.environ.get("PROMETHEUS_BASE_URL", "").rstrip("/")
        if not base_url:
            return ToolOutput.failure(
                "No metrics backend is configured (PROMETHEUS_BASE_URL is unset), so "
                "resource evidence is unavailable in this run. Do not assert memory "
                "or slot figures; if the failure looks resource-shaped, say so with "
                "reduced confidence.",
                source=source,
            )

        params: dict[str, Any] = {"query": query}
        lookback = max(0, min(int(args.get("lookback_minutes", 0) or 0), 1440))
        failed_at = ctx.incident.task_instance.end_date or ctx.incident.task_instance.start_date
        if failed_at is not None:
            params["time"] = failed_at.timestamp() - lookback * 60

        try:
            response = httpx.get(f"{base_url}/api/v1/query", params=params, timeout=15.0)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return ToolOutput.failure(f"metrics query failed: {exc}", source=source)

        if payload.get("status") != "success":
            return ToolOutput.failure(
                f"metrics backend rejected the query: {payload.get('error', 'unknown error')}",
                source=source,
            )

        series = payload.get("data", {}).get("result", [])
        if not series:
            return ToolOutput(
                content=f"{query!r} returned no series at the evaluated time.",
                source=source,
            )

        rows = [
            f"{item.get('metric', {})} = {(item.get('value') or ['', 'n/a'])[1]}"
            for item in series[:MAX_SERIES]
        ]
        header = f"{len(series)} series for {query!r}" + (
            f" (showing {MAX_SERIES})" if len(series) > MAX_SERIES else ""
        )
        return ToolOutput(content=f"{header}\n" + "\n".join(rows), source=source)
