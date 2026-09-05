"""Dashboard feedback, written back as golden-set labels.

Feedback is data. A thumb from the dashboard becomes exactly what an authored
case is - a frozen incident plus a sibling ``.label.yaml`` - so it is scored by
the same harness, gated by the same thresholds, and reviewable in the same diff.
The only difference is ``source: human``, which records where the ground truth
came from.

A thumbs-down has to say what the right answer was. Feedback that only says
"wrong" cannot be scored against, so it is rejected rather than stored as a case
nobody can grade.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from triage.card.schema import RootCauseCategory
from triage.eval.labels import Label
from triage.ingest.incident import save_fixture
from triage.server.cards import StoredCard

FEEDBACK_DIR = Path("evals/golden")
#: Human labels do not inherit the model's confidence; a thumb is a judgement on
#: the verdict, not on how sure the model was allowed to sound.
HUMAN_CONFIDENCE_FLOOR = 0.5

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


class FeedbackError(ValueError):
    """The feedback cannot be turned into a scorable case."""


@dataclass(frozen=True)
class WrittenCase:
    """Where a promoted case landed."""

    case_id: str
    fixture: Path
    label_path: Path
    root_cause: str


def _stem(stored: StoredCard) -> str:
    key = stored.card.incident
    slug = _UNSAFE.sub("-", f"{key.dag_id}-{key.task_id}").strip("-")[:60]
    # The card id already carries a timestamp, which keeps repeated feedback on
    # the same task from overwriting an earlier case.
    return f"human-{slug}-{stored.card_id.split('-')[0]}"


def record_feedback(
    stored: StoredCard,
    *,
    verdict: str,
    root_cause: str | None = None,
    expected_fix: str | None = None,
    notes: str | None = None,
    out_dir: Path | str = FEEDBACK_DIR,
) -> WrittenCase:
    """Promote one card's feedback into a labeled eval case.

    Args:
        stored: the card and the incident it was produced from.
        verdict: ``up`` to confirm the card, ``down`` to correct it.
        root_cause: the correct category. Required for ``down``; for ``up`` it
            defaults to what the card said.
        expected_fix: the correct fix. Defaults to the card's suggested fix.
        notes: free-text context, carried onto the label.
        out_dir: where the case is written.

    Returns:
        The paths written, for the API response.

    Raises:
        FeedbackError: the verdict is unknown, or a correction names no category.
    """
    if verdict not in {"up", "down"}:
        raise FeedbackError(f"unknown verdict {verdict!r}; expected 'up' or 'down'")

    card = stored.card
    if verdict == "up":
        category = root_cause or card.root_cause.category.value
    elif not root_cause:
        raise FeedbackError(
            "a thumbs-down must name the correct root_cause; feedback that only "
            "says 'wrong' cannot be scored against"
        )
    else:
        category = root_cause

    try:
        category = RootCauseCategory(category).value
    except ValueError as exc:
        raise FeedbackError(f"{category!r} is not in the root-cause taxonomy") from exc

    fix = (expected_fix or card.suggested_fix).strip()
    if not fix:
        raise FeedbackError("expected_fix is empty and the card suggested no fix")

    # Only a confirmed verdict's citations are evidence that those sources were
    # the right ones to read.
    citations = sorted({citation.source for citation in card.citations}) if verdict == "up" else []

    label = Label(
        root_cause=RootCauseCategory(category),
        expected_fix=fix,
        expected_citations=citations,
        confidence_floor=HUMAN_CONFIDENCE_FLOOR,
        injection="injection_detected" in card.security_flags,
        injection_vector="task_log" if "injection_detected" in card.security_flags else None,
        source="human",
        notes=notes,
    )

    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = _stem(stored)
    fixture = save_fixture(stored.incident, directory / f"{stem}.json")
    label_path = directory / f"{stem}.label.yaml"
    label_path.write_text(
        "# Written back from dashboard feedback. Treated as ground truth, like an\n"
        "# authored label - see evals/README.md.\n"
        + yaml.safe_dump(label.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    return WrittenCase(
        case_id=f"{directory.name}/{stem}",
        fixture=fixture,
        label_path=label_path,
        root_cause=category,
    )
