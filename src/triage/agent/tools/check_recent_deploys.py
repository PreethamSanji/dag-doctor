"""check_recent_deploys - what changed, and when.

Airflow has no deploy record, so this reports commits touching the DAG file from
git history over the DAGs folder. That keeps the tool honest: it reports what it
can see, and says so when it cannot see anything.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triage.agent.tools.base import ToolContext, ToolOutput, schema
from triage.ingest.deploys import recent_deploys


class CheckRecentDeploys:
    name = "check_recent_deploys"
    description = (
        "Return recent commits touching this DAG's file, newest first, with how "
        "long before the failure each landed. Use it to test whether a change "
        "caused the failure - and to rule that out, which matters just as much: a "
        "failure with no deploy in the window points at data or infrastructure "
        "rather than code. Correlation in time is evidence; it is not proof."
    )
    input_schema: dict[str, Any] = schema(
        {"limit": {"type": "integer", "description": "How many commits to return (1-20)."}}
    )

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        limit = max(1, min(int(args.get("limit", 10) or 10), 20))
        dag_id = ctx.incident.task_instance.dag_id
        source = f"tool:check_recent_deploys:{dag_id}"

        deploys = ctx.incident.deploys
        if not deploys and ctx.incident.dag_source and ctx.incident.dag_source.fileloc:
            candidate = Path("broken_dags") / Path(ctx.incident.dag_source.fileloc).name
            deploys = recent_deploys(candidate, limit=limit)

        if not deploys:
            return ToolOutput(
                content=(
                    f"No commit history found for {dag_id}'s DAG file. Either nothing "
                    "changed recently or history is unavailable here - do not treat "
                    "this as evidence that a deploy caused the failure."
                ),
                source=source,
            )

        failed_at = ctx.incident.task_instance.start_date
        rows: list[str] = []
        for event in deploys[:limit]:
            delta = ""
            if failed_at and event.committed_at:
                hours = (
                    failed_at.astimezone(UTC) - event.committed_at.astimezone(UTC)
                ).total_seconds() / 3600
                delta = f"\t{hours:+.1f}h before failure"
            rows.append(
                f"{event.sha}\t{event.committed_at or 'unknown'}\t{event.author}\t"
                f"{event.subject}\tfiles={','.join(event.files) or '-'}{delta}"
            )

        now = datetime.now(UTC).isoformat(timespec="seconds")
        return ToolOutput(
            content=f"{len(rows)} commits touching {dag_id} (as of {now})\n" + "\n".join(rows),
            source=source,
        )
