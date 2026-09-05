"""get_task_history - did this task used to work?

The single most discriminating question in Airflow triage. A task that succeeded
on the same code yesterday points at data or infrastructure; a task that has
never succeeded points at code or configuration.
"""

from __future__ import annotations

from typing import Any

from triage.agent.tools.base import ToolContext, ToolOutput, schema
from triage.ingest.airflow_client import AirflowError


class GetTaskHistory:
    name = "get_task_history"
    description = (
        "Return recent runs of this same task across DAG runs: state, try number, "
        "start time, and duration. Use it to answer 'would the same code have "
        "succeeded on yesterday's input?' - a run of successes ending in one "
        "failure points at data or infrastructure, while a task that has never "
        "succeeded points at code or configuration. Duration trends also separate "
        "resource exhaustion from a fast configuration failure."
    )
    input_schema: dict[str, Any] = schema(
        {
            "limit": {
                "type": "integer",
                "description": "How many recent runs to return (1-25).",
            }
        }
    )

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        limit = max(1, min(int(args.get("limit", 10) or 10), 25))
        ti = ctx.incident.task_instance
        source = f"tool:get_task_history:{ti.dag_id}/{ti.task_id}"

        history = ctx.incident.history
        if not history and ctx.airflow is not None:
            try:
                history = ctx.airflow.get_task_history(ti.dag_id, ti.task_id, limit=limit)
            except AirflowError as exc:
                return ToolOutput.failure(f"history unavailable: {exc}", source=source)

        if not history:
            return ToolOutput(
                content=(
                    f"No prior runs recorded for {ti.dag_id}.{ti.task_id}. "
                    "This may be the task's first execution, or history was not ingested."
                ),
                source=source,
            )

        rows = [
            f"{run.run_id}\tstate={run.state}\ttry={run.try_number}\t"
            f"started={run.start_date}\tduration_s={run.duration}"
            for run in history[:limit]
        ]
        states = [(run.state or "unknown").lower() for run in history[:limit]]
        successes = states.count("success")
        summary = (
            f"{len(rows)} recent runs of {ti.dag_id}.{ti.task_id}: "
            f"{successes} success, {len(rows) - successes} non-success."
        )
        return ToolOutput(content=f"{summary}\n" + "\n".join(rows), source=source)
