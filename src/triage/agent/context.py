"""Building model context out of an incident.

This module is the only place raw incident content becomes prompt text, and it
never concatenates raw tool output: every untrusted piece goes through
:func:`triage.security.sanitize.sanitize` first and is registered in the
evidence index under the same id the model is told to cite.

Airflow metadata is handled separately and structurally. It is rendered as
key/value lines outside any untrusted block, with free-text fields scrubbed,
because task state must not be assertable by log content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from triage.card.citations import EvidenceIndex
from triage.config import Config
from triage.ingest.models import Incident
from triage.retrieval.store import SearchResult
from triage.security.sanitize import Sanitized, sanitize

_CONTROL = re.compile(r"[\r\n\t]+")


def _scrub(value: object, limit: int = 200) -> str:
    """Flatten a free-text metadata field so it cannot forge structure."""
    text = _CONTROL.sub(" ", str(value if value is not None else "-")).strip()
    return text[:limit] if text else "-"


@dataclass
class IncidentContext:
    """Prompt-ready context for one incident, plus what it takes to verify it."""

    metadata: str
    blocks: list[Sanitized] = field(default_factory=list)
    index: EvidenceIndex = field(default_factory=EvidenceIndex)
    security_flags: list[str] = field(default_factory=list)

    def render(self) -> str:
        parts = [self.metadata, *(block.text for block in self.blocks)]
        return "\n\n".join(parts)


def render_metadata(incident: Incident) -> str:
    """Structural facts, straight from the Airflow API. Never from log text."""
    ti = incident.task_instance
    lines = [
        "## Airflow metadata (authoritative - from the Airflow REST API)",
        f"dag_id: {_scrub(ti.dag_id)}",
        f"task_id: {_scrub(ti.task_id)}",
        f"run_id: {_scrub(ti.run_id)}",
        f"try_number: {ti.try_number} of max_tries {ti.max_tries if ti.max_tries else '-'}",
        f"state: {_scrub(ti.state)}",
        f"operator: {_scrub(ti.operator)}",
        f"duration_seconds: {ti.duration if ti.duration is not None else '-'}",
        f"pool: {_scrub(ti.pool)}",
        f"queue: {_scrub(ti.queue)}",
        f"hostname: {_scrub(ti.hostname)}",
    ]
    if incident.dag_source:
        lines.append(f"dag_file: {_scrub(incident.dag_source.fileloc)}")
    if ti.note:
        lines.append(f"note (operator-supplied, untrusted): {_scrub(ti.note)}")
    return "\n".join(lines)


def _add_block(
    context: IncidentContext,
    content: str,
    *,
    chunk_id: str,
    kind: str,
    source: str,
    max_chars: int,
) -> None:
    if not content.strip():
        return
    block = sanitize(
        content, kind=kind, source=f"{source} | chunk_id={chunk_id}", max_chars=max_chars
    )
    context.blocks.append(block)
    context.index.add(chunk_id, block.text, source)
    for flag in block.flags:
        if flag not in context.security_flags:
            context.security_flags.append(flag)


def build_incident_context(incident: Incident, config: Config) -> IncidentContext:
    """Sanitize every untrusted part of an incident into citable blocks."""
    context = IncidentContext(metadata=render_metadata(incident))
    caps = config.security

    _add_block(
        context,
        incident.log.tail(config.ingest.log_tail_lines),
        chunk_id="incident:log",
        kind="task_log",
        source=f"airflow:log:{incident.key}",
        max_chars=caps.max_untrusted_chars,
    )

    if incident.dag_source:
        _add_block(
            context,
            incident.dag_source.source,
            chunk_id="incident:dag_source",
            kind="dag_source",
            source=f"airflow:dag_source:{incident.dag_source.fileloc}",
            max_chars=caps.max_untrusted_chars,
        )

    if incident.history:
        rendered = "\n".join(
            f"{run.run_id}\ttry={run.try_number}\tstate={run.state}\t"
            f"duration={run.duration}\tstarted={run.start_date}"
            for run in incident.history
        )
        _add_block(
            context,
            rendered,
            chunk_id="incident:history",
            kind="task_history",
            source=f"airflow:history:{incident.task_instance.dag_id}",
            max_chars=caps.max_field_chars,
        )

    if incident.deploys:
        rendered = "\n".join(
            f"{event.sha}\t{event.committed_at}\t{event.author}\t{event.subject}\t"
            f"files={','.join(event.files)}"
            for event in incident.deploys
        )
        _add_block(
            context,
            rendered,
            chunk_id="incident:deploys",
            kind="deploy_history",
            source="git:broken_dags",
            max_chars=caps.max_field_chars,
        )

    if incident.import_errors:
        _add_block(
            context,
            "\n".join(incident.import_errors),
            chunk_id="incident:import_errors",
            kind="import_errors",
            source="airflow:importErrors",
            max_chars=caps.max_field_chars,
        )

    return context


def add_retrieval(
    context: IncidentContext,
    results: list[SearchResult],
    config: Config,
) -> None:
    """Fold retrieved corpus chunks into the context under their own chunk ids."""
    for result in results:
        chunk = result.chunk
        _add_block(
            context,
            f"{chunk.header}\n\n{chunk.text}",
            chunk_id=chunk.chunk_id,
            kind="doc_chunk",
            source=chunk.source,
            max_chars=config.security.max_field_chars,
        )


def retrieval_query(incident: Incident, config: Config) -> str:
    """Build the retrieval query from the failure signature, not the whole log.

    The last lines of an Airflow task log are where the traceback lands, so the
    tail plus the task identity is a better query than the full log body.
    """
    ti = incident.task_instance
    tail = incident.log.tail(40)
    return f"{ti.dag_id} {ti.task_id} {ti.operator or ''}\n{tail}"[
        : config.security.max_field_chars
    ]
