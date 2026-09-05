"""Parsing and grounding the model's verdict.

Structured output or fail loudly: a verdict that does not parse against
:class:`~triage.card.schema.TriageVerdict` gets exactly one structured retry,
then becomes a parse-error card. Parse failures are an eval metric, not a crash.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from triage.card.citations import EvidenceIndex, ValidationResult, validate_citations
from triage.card.schema import TriageVerdict
from triage.llm import Completion

RETRY_INSTRUCTION = (
    "Your previous response did not parse against the required verdict schema.\n"
    "Error: {error}\n\n"
    "Reply with the verdict object only - a single JSON object, no prose, no "
    "markdown fences, no trailing text. Use only the allowed root_cause "
    "categories, and cite only chunk ids that appear in the context above."
)


class VerdictParseError(ValueError):
    """The model's response was not a schema-valid verdict."""


def parse_verdict(completion: Completion) -> TriageVerdict:
    """Parse one completion into a verdict, or raise :class:`VerdictParseError`."""
    text = completion.text
    if not text:
        raise VerdictParseError("response contained no text block")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        payload = _salvage_json(text)
        if payload is None:
            raise VerdictParseError(f"response was not JSON: {exc}") from exc
    try:
        return TriageVerdict.model_validate(payload)
    except ValidationError as exc:
        raise VerdictParseError(f"verdict failed schema validation: {exc}") from exc


def _salvage_json(text: str) -> dict | None:
    """Recover a JSON object from a response wrapped in prose or fences.

    Structured output should make this unnecessary; it exists so a formatting
    slip degrades into a valid card instead of a crash, and so the retry is
    spent on genuinely malformed output.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def ground_verdict(
    verdict: TriageVerdict, index: EvidenceIndex
) -> tuple[TriageVerdict, ValidationResult]:
    """Replace the verdict's citations with only those that resolve to real chunks."""
    result = validate_citations(verdict.citations, index)
    grounded = verdict.model_copy(update={"citations": result.kept})
    return grounded, result
