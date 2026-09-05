"""fetch_dag_source - read the DAG file.

The DAG file is code, and code is untrusted input like anything else: a comment
or a docstring in a DAG can carry an injection payload just as a log line can.
Sanitization happens in the loop, on this tool's output, with no exemption.
"""

from __future__ import annotations

from typing import Any

from triage.agent.tools.base import ToolContext, ToolOutput, schema
from triage.ingest.airflow_client import AirflowError

MAX_LINES = 200


class FetchDagSource:
    name = "fetch_dag_source"
    description = (
        "Return the source of the DAG file that defines this task, optionally "
        "only the lines around a search term. Use it to check what a frame in the "
        "traceback actually does, to see whether a lookup has a default, or to "
        "confirm whether an import sits at module level (parse-time failure, "
        "affects every task in the file) or inside a task (runtime failure, "
        "affects one task). Prefer a search term over the whole file."
    )
    input_schema: dict[str, Any] = schema(
        {
            "search": {
                "type": "string",
                "description": (
                    "Optional literal substring; only lines containing it, with "
                    "surrounding context, are returned. Omit for the whole file."
                ),
            },
            "context_lines": {
                "type": "integer",
                "description": "Lines of context around each hit when searching (0-20).",
            },
        }
    )

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        dag_id = ctx.incident.task_instance.dag_id
        dag_source = ctx.incident.dag_source
        source = f"tool:fetch_dag_source:{dag_id}"

        if dag_source is None and ctx.airflow is not None:
            try:
                dag_source = ctx.airflow.get_dag_source(dag_id)
            except AirflowError as exc:
                return ToolOutput.failure(f"DAG source unavailable: {exc}", source=source)

        if dag_source is None:
            return ToolOutput.failure(
                f"No DAG source available for {dag_id}. Diagnose from the log and "
                "metadata, and lower confidence accordingly.",
                source=source,
            )

        source = f"tool:fetch_dag_source:{dag_source.fileloc or dag_id}"
        lines = dag_source.source.splitlines()
        search = str(args.get("search", "") or "").strip()

        if not search:
            body = "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines[:MAX_LINES]))
            suffix = (
                f"\n...[{len(lines) - MAX_LINES} more lines; search to see them]"
                if len(lines) > MAX_LINES
                else ""
            )
            return ToolOutput(
                content=f"{dag_source.fileloc} ({len(lines)} lines)\n{body}{suffix}",
                source=source,
            )

        context_lines = max(0, min(int(args.get("context_lines", 4) or 0), 20))
        hits = [i for i, line in enumerate(lines) if search.lower() in line.lower()]
        if not hits:
            return ToolOutput(
                content=f"{dag_source.fileloc}: no line contains {search!r}.",
                source=source,
            )

        rendered: list[str] = []
        last_end = -1
        for index in hits[:20]:
            start = max(0, index - context_lines)
            end = min(len(lines), index + context_lines + 1)
            if start > last_end + 1 and rendered:
                rendered.append("--")
            for line_no in range(max(start, last_end + 1), end):
                marker = ">" if line_no == index else " "
                rendered.append(f"{marker}{line_no + 1}: {lines[line_no]}")
            last_end = end - 1

        return ToolOutput(
            content=(
                f"{dag_source.fileloc}: {len(hits)} lines contain {search!r}\n"
                + "\n".join(rendered)
            ),
            source=source,
        )
