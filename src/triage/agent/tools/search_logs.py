"""search_logs - find lines in the task log without reading all of it."""

from __future__ import annotations

import re
from typing import Any

from triage.agent.tools.base import ToolContext, ToolOutput, schema

MAX_MATCHES = 40


class SearchLogs:
    name = "search_logs"
    description = (
        "Search this task instance's log for a regular expression and return the "
        "matching lines with surrounding context. Use it to test a specific "
        "hypothesis - the raising frame, an exit code, a resource message, the "
        "lines immediately before a traceback - rather than to re-read the log. "
        "Returns the match count, which is itself evidence: zero matches for a "
        "signature you expected is a result worth reasoning about."
    )
    input_schema: dict[str, Any] = schema(
        {
            "pattern": {
                "type": "string",
                "description": (
                    "Python regular expression, case-insensitive. Examples: "
                    "'Traceback', 'return code', 'KeyError|ModuleNotFoundError', "
                    "'SIGKILL|SIGTERM'."
                ),
            },
            "context_lines": {
                "type": "integer",
                "description": "Lines of context to show around each match (0-10).",
            },
        },
        required=["pattern"],
    )

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        pattern = str(args.get("pattern", "")).strip()
        source = f"tool:search_logs:{ctx.incident.key}"
        if not pattern:
            return ToolOutput.failure("pattern is required", source=source)

        context_lines = max(0, min(int(args.get("context_lines", 2) or 0), 10))
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return ToolOutput.failure(f"invalid regular expression: {exc}", source=source)

        lines = ctx.incident.log.content.splitlines()
        hits = [index for index, line in enumerate(lines) if regex.search(line)]
        if not hits:
            return ToolOutput(
                content=(
                    f"0 lines of {len(lines)} match /{pattern}/. "
                    "The log does not contain this signature."
                ),
                source=source,
            )

        rendered: list[str] = []
        last_end = -1
        for index in hits[:MAX_MATCHES]:
            start = max(0, index - context_lines)
            end = min(len(lines), index + context_lines + 1)
            if start > last_end + 1 and rendered:
                rendered.append("--")
            for line_no in range(max(start, last_end + 1), end):
                marker = ">" if line_no == index else " "
                rendered.append(f"{marker}{line_no + 1}: {lines[line_no]}")
            last_end = end - 1

        header = f"{len(hits)} of {len(lines)} log lines match /{pattern}/" + (
            f" (showing first {MAX_MATCHES})" if len(hits) > MAX_MATCHES else ""
        )
        return ToolOutput(content=f"{header}\n" + "\n".join(rendered), source=source)
