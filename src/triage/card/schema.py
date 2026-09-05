"""Triage-card schema - the single source of truth for verdict shape.

Two models live here and the split is the point:

* :class:`TriageVerdict` is what the *model* is allowed to produce. Its JSON
  schema is what we hand to structured outputs.
* :class:`TriageCard` is what we *emit*. Everything on it that can be derived
  from Airflow API metadata instead of from log text is derived that way - the
  first layer of the defense-in-depth model. A log line cannot assert that a
  task succeeded, because ``incident.state`` never comes from the log.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RootCauseCategory(StrEnum):
    """Closed taxonomy. Labels and eval scoring share this exact label space."""

    CODE_ERROR = "code_error"
    CONFIG_ERROR = "config_error"
    UPSTREAM_DATA = "upstream_data"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    DEPENDENCY_ERROR = "dependency_error"
    EXTERNAL_SERVICE = "external_service"
    PLATFORM_ERROR = "platform_error"


TAXONOMY: tuple[str, ...] = tuple(c.value for c in RootCauseCategory)


class Citation(BaseModel):
    """A pointer to evidence that was in context during this run.

    ``chunk_id`` must resolve against the run's retrieved chunks or the evidence
    trail; ``quote`` must appear in that chunk. Unresolvable citations are
    dropped by :mod:`triage.card.citations` and cost groundedness.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="Provenance, e.g. corpus/helm/values.yaml or tool:search_logs")
    chunk_id: str = Field(description="Identifier of the chunk or tool result quoted")
    quote: str = Field(description="Verbatim span from that chunk supporting the claim")


class RootCause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: RootCauseCategory
    hypothesis: str = Field(description="One or two sentences naming the concrete failure")
    confidence: float = Field(ge=0.0, le=1.0)


class TriageVerdict(BaseModel):
    """The model-produced part of a card. Structured output validates against this."""

    model_config = ConfigDict(extra="forbid")

    root_cause: RootCause
    suggested_fix: str = Field(description="Concrete, actionable remediation")
    citations: list[Citation] = Field(default_factory=list)
    insufficient_evidence: bool = Field(
        default=False,
        description="True when the loop exhausted its step budget without converging",
    )

    @field_validator("citations")
    @classmethod
    def _cap_citations(cls, value: list[Citation]) -> list[Citation]:
        return value[:12]


class EvidenceStep(BaseModel):
    """One (tool, args, result-digest) triple from the agent loop."""

    model_config = ConfigDict(extra="forbid")

    step: int
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    result_digest: str = Field(description="Truncated, sanitized summary of the tool result")
    chunk_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    latency_ms: int | None = None


class IncidentKey(BaseModel):
    """Identity of the failure being triaged. Always from the Airflow API."""

    model_config = ConfigDict(extra="forbid")

    dag_id: str
    task_id: str
    run_id: str
    try_number: int = 1

    def __str__(self) -> str:
        return f"{self.dag_id}/{self.task_id}/{self.run_id}#{self.try_number}"


class RunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    mode: str = "agent"
    steps_used: int = 0
    max_steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    config_fingerprint: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TriageCard(BaseModel):
    """The artifact. Everything downstream - CLI, evals, dashboard - reads this."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    incident: IncidentKey
    root_cause: RootCause
    suggested_fix: str
    citations: list[Citation] = Field(default_factory=list)
    evidence_trail: list[EvidenceStep] = Field(default_factory=list)
    security_flags: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False
    parse_error: str | None = Field(
        default=None,
        description="Set when structured output failed twice; the card is still valid JSON",
    )
    run: RunMetadata

    @classmethod
    def from_verdict(
        cls,
        verdict: TriageVerdict,
        *,
        incident: IncidentKey,
        evidence_trail: list[EvidenceStep],
        security_flags: list[str],
        run: RunMetadata,
    ) -> TriageCard:
        return cls(
            incident=incident,
            root_cause=verdict.root_cause,
            suggested_fix=verdict.suggested_fix,
            citations=verdict.citations,
            evidence_trail=evidence_trail,
            security_flags=security_flags,
            insufficient_evidence=verdict.insufficient_evidence,
            run=run,
        )

    @classmethod
    def parse_error_card(
        cls,
        *,
        incident: IncidentKey,
        error: str,
        evidence_trail: list[EvidenceStep],
        security_flags: list[str],
        run: RunMetadata,
    ) -> TriageCard:
        """Structured output failed after its retry. Fail loudly, but as a valid card.

        Parse failures are an eval metric, not a crash.
        """
        return cls(
            incident=incident,
            root_cause=RootCause(
                category=RootCauseCategory.PLATFORM_ERROR,
                hypothesis="Triage did not produce a schema-valid verdict.",
                confidence=0.0,
            ),
            suggested_fix="Re-run triage; inspect the evidence trail for the failing step.",
            citations=[],
            evidence_trail=evidence_trail,
            security_flags=security_flags,
            insufficient_evidence=True,
            parse_error=error[:2000],
            run=run,
        )


def verdict_json_schema() -> dict[str, Any]:
    """JSON schema handed to the Messages API via ``output_config.format``.

    Structured outputs require ``additionalProperties: false`` and explicit
    ``required`` on every object, which ``extra="forbid"`` gives us.
    """
    schema = TriageVerdict.model_json_schema()
    _strictify(schema)
    return schema


def _strictify(node: Any) -> None:
    """Recursively enforce the shape structured outputs expects."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = sorted(node["properties"].keys())
        for value in node.values():
            _strictify(value)
    elif isinstance(node, list):
        for item in node:
            _strictify(item)
