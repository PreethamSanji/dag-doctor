"""query_runbook - retrieval over the vendored corpus.

This is the tool that makes a claim citable. Every chunk it returns is
registered in the run's evidence index under its own stable chunk id, so the
model can quote it and the citation validator can verify the quote.
"""

from __future__ import annotations

from typing import Any

from triage.agent.tools.base import ToolContext, ToolOutput, schema


class QueryRunbook:
    name = "query_runbook"
    description = (
        "Search the documentation corpus - Airflow docs, Helm chart values, past "
        "postmortems, and review threads - and return the most relevant chunks "
        "with their chunk ids. This is the only source of citable external "
        "evidence: cite a chunk id returned here to ground a claim about what a "
        "log signature means or how a setting behaves. Query with the failure "
        "signature, not with your conclusion."
    )
    input_schema: dict[str, Any] = schema(
        {
            "query": {
                "type": "string",
                "description": (
                    "Search text. Prefer the observed signature - "
                    "'Negsignal.SIGKILL no traceback', "
                    "'Variable.get KeyError AIRFLOW_VAR' - over a category name."
                ),
            },
            "k": {"type": "integer", "description": "How many chunks to return (1-10)."},
        },
        required=["query"],
    )

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        source = "tool:query_runbook"
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolOutput.failure("query is required", source=source)
        if ctx.retriever is None:
            return ToolOutput.failure(
                "No retrieval index is available in this run. Any claim about "
                "documentation would be ungrounded.",
                source=source,
            )

        k = max(1, min(int(args.get("k", ctx.config.retrieval.k) or ctx.config.retrieval.k), 10))
        results = ctx.retriever.search(query, k=k)
        if not results:
            return ToolOutput(
                content=(
                    f"No corpus chunks matched {query!r}. The corpus may not cover "
                    "this failure mode; do not invent a citation."
                ),
                source=source,
            )

        # Register chunks by id so the model cites the chunk, not this tool call.
        ctx.extras.setdefault("retrieved_chunks", []).extend(result.chunk for result in results)

        rendered = [
            f"[chunk_id={result.chunk.chunk_id} score={result.score:.3f}]\n"
            f"{result.chunk.header}\n{result.chunk.text}"
            for result in results
        ]
        return ToolOutput(
            content=f"{len(results)} chunks for {query!r}\n\n" + "\n\n".join(rendered),
            source=source,
        )
