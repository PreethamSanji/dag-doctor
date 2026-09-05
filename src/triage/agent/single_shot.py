"""Single-shot triage (M1).

Retrieve once, ask once, validate the answer. This is the baseline the agent
loop has to beat, and it stays in the codebase for exactly that reason: an eval
run can compare ``mode: single_shot`` against ``mode: agent`` on the same golden
set and show what the loop actually buys.
"""

from __future__ import annotations

import time

from triage.agent.context import add_retrieval, build_incident_context, retrieval_query
from triage.agent.prompts import SYSTEM_PROMPT
from triage.agent.verdict import RETRY_INSTRUCTION, VerdictParseError, ground_verdict, parse_verdict
from triage.card.schema import (
    IncidentKey,
    RunMetadata,
    TriageCard,
    verdict_json_schema,
)
from triage.config import Config
from triage.ingest.models import Incident
from triage.llm import LLMClient, Usage
from triage.retrieval.retriever import Retriever

USER_TEMPLATE = """Triage this failed Airflow task instance.

{context}

Produce the verdict object now."""


def run_single_shot(
    incident: Incident,
    *,
    config: Config,
    client: LLMClient,
    retriever: Retriever | None = None,
) -> TriageCard:
    """Diagnose one incident with a single model call over retrieved context."""
    started = time.perf_counter()
    usage = Usage()

    context = build_incident_context(incident, config)
    if retriever is not None:
        results = retriever.search(retrieval_query(incident, config))
        add_retrieval(context, results, config)

    messages: list[dict] = [
        {"role": "user", "content": USER_TEMPLATE.format(context=context.render())}
    ]
    schema = verdict_json_schema()

    verdict = None
    parse_error: str | None = None
    for attempt in range(config.agent.structured_retries + 1):
        completion = client.complete(
            system=SYSTEM_PROMPT,
            messages=messages,
            output_schema=schema,
            max_tokens=config.agent.max_tokens,
        )
        usage.add(client.model, completion.input_tokens, completion.output_tokens)
        try:
            verdict = parse_verdict(completion)
            parse_error = None
            break
        except VerdictParseError as exc:
            parse_error = str(exc)
            if attempt >= config.agent.structured_retries:
                break
            messages.append({"role": "assistant", "content": completion.content})
            messages.append(
                {"role": "user", "content": RETRY_INSTRUCTION.format(error=parse_error)}
            )

    run = RunMetadata(
        model=client.model,
        mode="single_shot",
        steps_used=0,
        max_steps=0,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=round(usage.cost_usd, 6),
        latency_ms=int((time.perf_counter() - started) * 1000),
        config_fingerprint=config.fingerprint,
    )
    key = IncidentKey(
        dag_id=incident.task_instance.dag_id,
        task_id=incident.task_instance.task_id,
        run_id=incident.task_instance.run_id,
        try_number=incident.task_instance.try_number or 1,
    )

    if verdict is None:
        return TriageCard.parse_error_card(
            incident=key,
            error=parse_error or "unknown parse failure",
            evidence_trail=[],
            security_flags=context.security_flags,
            run=run,
        )

    grounded, validation = ground_verdict(verdict, context.index)
    return TriageCard.from_verdict(
        grounded,
        incident=key,
        evidence_trail=[],
        security_flags=context.security_flags + validation.flags,
        run=run,
    )
