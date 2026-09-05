"""The agent loop (M2).

Hypothesis -> gather evidence -> narrow -> verdict, bounded at ``max_steps``.
The loop is the product, not a wrapper around one call, and three properties are
enforced here rather than requested in the prompt:

* **Every tool result is sanitized before it enters context.** The loop, not the
  tool, wraps output in an untrusted-data block, neutralizes instruction-like
  spans, and unions the resulting flags onto the card. ``fetch_dag_source`` gets
  no exemption for being code.
* **Every result is citable and verifiable.** Each result is registered in the
  evidence index under the chunk id the model is shown, and chunks surfaced by
  ``query_runbook`` are registered individually under their corpus ids.
* **Exhaustion is honest.** Running out of steps produces a verdict with
  ``insufficient_evidence: true`` and a capped confidence - the model cannot
  claim certainty it did not earn.

The full ``(tool, args, result-digest)`` trace ships in the card as
``evidence_trail``.
"""

from __future__ import annotations

import json
import time
from typing import Any

from triage.agent.context import IncidentContext, build_incident_context
from triage.agent.prompts import AGENT_SYSTEM_PROMPT
from triage.agent.tools import Tool, ToolContext, default_registry, digest, tool_specs
from triage.agent.verdict import (
    RETRY_INSTRUCTION,
    VerdictParseError,
    ground_verdict,
    parse_verdict,
)
from triage.card.schema import (
    EvidenceStep,
    IncidentKey,
    RunMetadata,
    TriageCard,
    TriageVerdict,
    verdict_json_schema,
)
from triage.config import Config
from triage.ingest.airflow_client import AirflowClient
from triage.ingest.models import Incident
from triage.llm import Completion, LLMClient, Usage
from triage.retrieval.retriever import Retriever
from triage.security.sanitize import sanitize

USER_TEMPLATE = """Triage this failed Airflow task instance.

{context}

Work the loop: form a hypothesis from the failure signature, use tools to gather
the evidence that would confirm or kill it, then commit to a verdict. You have
at most {max_steps} tool-calling steps."""

EXHAUSTION_INSTRUCTION = (
    "You have used all {max_steps} evidence-gathering steps. Stop calling tools "
    "and emit the verdict object now, based only on what you actually gathered. "
    "Set insufficient_evidence to true and choose a confidence that reflects what "
    "is still unresolved."
)

#: Confidence ceiling applied when the loop exhausted its step budget.
EXHAUSTED_CONFIDENCE_CEILING = 0.5


def run_agent(
    incident: Incident,
    *,
    config: Config,
    client: LLMClient,
    retriever: Retriever | None = None,
    airflow: AirflowClient | None = None,
    registry: dict[str, Tool] | None = None,
) -> TriageCard:
    """Diagnose one incident with the bounded multi-step loop."""
    started = time.perf_counter()
    usage = Usage()
    tools = registry if registry is not None else default_registry()
    specs = tool_specs(tools)
    schema = verdict_json_schema()

    context = build_incident_context(incident, config)
    tool_ctx = ToolContext(incident=incident, config=config, retriever=retriever, airflow=airflow)

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": USER_TEMPLATE.format(
                context=context.render(), max_steps=config.agent.max_steps
            ),
        }
    ]
    trail: list[EvidenceStep] = []
    steps_used = 0
    final: Completion | None = None

    while steps_used < config.agent.max_steps:
        completion = client.complete(
            system=AGENT_SYSTEM_PROMPT,
            messages=messages,
            tools=specs,
            output_schema=schema,
            max_tokens=config.agent.max_tokens,
        )
        usage.add(client.model, completion.input_tokens, completion.output_tokens)

        calls = completion.tool_calls
        if not calls:
            final = completion
            break

        steps_used += 1
        messages.append({"role": "assistant", "content": completion.content})
        results: list[dict[str, Any]] = []
        for call in calls:
            step, result_block = _execute(
                call,
                tools=tools,
                tool_ctx=tool_ctx,
                context=context,
                config=config,
                step=steps_used,
            )
            trail.append(step)
            results.append(result_block)
        messages.append({"role": "user", "content": results})

    exhausted = final is None
    if exhausted:
        messages.append(
            {
                "role": "user",
                "content": EXHAUSTION_INSTRUCTION.format(max_steps=config.agent.max_steps),
            }
        )

    verdict, parse_error = _finalize(
        client,
        messages=messages,
        specs=specs,
        schema=schema,
        config=config,
        usage=usage,
        candidate=final,
    )

    run = RunMetadata(
        model=client.model,
        mode="agent",
        steps_used=steps_used,
        max_steps=config.agent.max_steps,
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
            evidence_trail=trail,
            security_flags=context.security_flags,
            run=run,
        )

    if exhausted:
        verdict = _mark_exhausted(verdict)

    grounded, validation = ground_verdict(verdict, context.index)
    return TriageCard.from_verdict(
        grounded,
        incident=key,
        evidence_trail=trail,
        security_flags=context.security_flags + validation.flags,
        run=run,
    )


def _execute(
    call: dict[str, Any],
    *,
    tools: dict[str, Tool],
    tool_ctx: ToolContext,
    context: IncidentContext,
    config: Config,
    step: int,
) -> tuple[EvidenceStep, dict[str, Any]]:
    """Run one tool call, sanitize its output, and make it citable."""
    name = call.get("name", "")
    args = call.get("input") or {}
    if not isinstance(args, dict):
        args = {}
    started = time.perf_counter()

    tool = tools.get(name)
    if tool is None:
        message = f"Unknown tool {name!r}. Available tools: {', '.join(sorted(tools))}."
        return (
            EvidenceStep(
                step=step,
                tool=name or "<unnamed>",
                args=args,
                result_digest=message,
                error=message,
                latency_ms=0,
            ),
            {
                "type": "tool_result",
                "tool_use_id": call.get("id", ""),
                "content": message,
                "is_error": True,
            },
        )

    try:
        output = tool.run(args, tool_ctx)
    except Exception as exc:  # a tool crash is evidence, not a run-ending failure
        output_error = f"{type(exc).__name__}: {exc}"
        return (
            EvidenceStep(
                step=step,
                tool=name,
                args=args,
                result_digest=output_error,
                error=output_error,
                latency_ms=int((time.perf_counter() - started) * 1000),
            ),
            {
                "type": "tool_result",
                "tool_use_id": call.get("id", ""),
                "content": f"Tool {name} failed: {output_error}",
                "is_error": True,
            },
        )

    chunk_id = f"tool:{name}:{step}"
    block = _register(
        context,
        output.content,
        chunk_id=chunk_id,
        kind=name,
        source=output.source,
        max_chars=config.security.max_tool_result_chars,
    )
    chunk_ids = [chunk_id, *_register_retrieved(context, tool_ctx, config)]

    return (
        EvidenceStep(
            step=step,
            tool=name,
            args=args,
            result_digest=digest(output.content),
            chunk_ids=chunk_ids,
            error=output.error,
            latency_ms=int((time.perf_counter() - started) * 1000),
        ),
        {
            "type": "tool_result",
            "tool_use_id": call.get("id", ""),
            "content": block,
            "is_error": output.failed,
        },
    )


def _register(
    context: IncidentContext,
    content: str,
    *,
    chunk_id: str,
    kind: str,
    source: str,
    max_chars: int,
) -> str:
    """Sanitize content, add it to the evidence index, and return the block text."""
    block = sanitize(
        content,
        kind=kind,
        source=f"{source} | chunk_id={chunk_id}",
        max_chars=max_chars,
    )
    context.blocks.append(block)
    context.index.add(chunk_id, block.text, source)
    for flag in block.flags:
        if flag not in context.security_flags:
            context.security_flags.append(flag)
    return block.text


def _register_retrieved(
    context: IncidentContext, tool_ctx: ToolContext, config: Config
) -> list[str]:
    """Register corpus chunks surfaced by query_runbook under their own ids."""
    pending = tool_ctx.extras.pop("retrieved_chunks", [])
    registered: list[str] = []
    for chunk in pending:
        if chunk.chunk_id in context.index:
            continue
        _register(
            context,
            f"{chunk.header}\n\n{chunk.text}",
            chunk_id=chunk.chunk_id,
            kind="doc_chunk",
            source=chunk.source,
            max_chars=config.security.max_field_chars,
        )
        registered.append(chunk.chunk_id)
    return registered


def _finalize(
    client: LLMClient,
    *,
    messages: list[dict[str, Any]],
    specs: list[dict[str, Any]],
    schema: dict[str, Any],
    config: Config,
    usage: Usage,
    candidate: Completion | None,
) -> tuple[TriageVerdict | None, str | None]:
    """Parse the verdict, spending at most ``structured_retries`` extra requests."""
    parse_error: str | None = None
    # The loop's own candidate counts as attempt one.
    attempts = config.agent.structured_retries + 1

    if candidate is not None:
        try:
            return parse_verdict(candidate), None
        except VerdictParseError as exc:
            parse_error = str(exc)
            attempts -= 1
            messages.append({"role": "assistant", "content": candidate.content})
            messages.append(
                {"role": "user", "content": RETRY_INSTRUCTION.format(error=parse_error)}
            )

    if attempts <= 0:
        return None, parse_error
    for attempt in range(attempts):
        completion = client.complete(
            system=AGENT_SYSTEM_PROMPT,
            messages=messages,
            tools=specs,
            output_schema=schema,
            tool_choice={"type": "none"},
            max_tokens=config.agent.max_tokens,
        )
        usage.add(client.model, completion.input_tokens, completion.output_tokens)
        try:
            return parse_verdict(completion), None
        except VerdictParseError as exc:
            parse_error = str(exc)
            if attempt >= attempts - 1:
                break
            messages.append({"role": "assistant", "content": completion.content})
            messages.append(
                {"role": "user", "content": RETRY_INSTRUCTION.format(error=parse_error)}
            )

    return None, parse_error


def _mark_exhausted(verdict: TriageVerdict) -> TriageVerdict:
    """A verdict reached by running out of steps cannot claim high confidence."""
    root_cause = verdict.root_cause.model_copy(
        update={"confidence": min(verdict.root_cause.confidence, EXHAUSTED_CONFIDENCE_CEILING)}
    )
    return verdict.model_copy(update={"root_cause": root_cause, "insufficient_evidence": True})


def trail_to_json(trail: list[EvidenceStep]) -> str:
    """Compact rendering of the evidence trail, for logs and eval reports."""
    return json.dumps([step.model_dump(mode="json") for step in trail], indent=2)
