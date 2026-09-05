"""The golden set: fixtures paired with authored ground truth.

The rule that makes the golden set CI-enforceable rather than aspirational is
mechanical: an incident fixture with no sibling ``.label.yaml`` is not an eval
case, it is an error. :func:`discover_cases` raises on one, so a fixture cannot
be quietly added to the suite without someone writing down what the right answer
is.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from triage.card.schema import RootCauseCategory

GOLDEN_DIR = Path("evals/golden")
INJECTION_DIR = Path("evals/injection")
LABEL_SUFFIX = ".label.yaml"


class UnlabeledFixtureError(ValueError):
    """An incident fixture has no sibling label file. No label, no eval case."""


class Label(BaseModel):
    """Ground truth for one incident fixture.

    ``expected_citations`` entries are matched as prefixes against both the
    citation's source and its chunk id, so a label can name a corpus document
    (``corpus/helm/values.yaml``) or an incident block (``incident:log``).
    """

    model_config = ConfigDict(extra="forbid")

    root_cause: RootCauseCategory
    expected_fix: str
    fix_keywords: list[str] = Field(
        default_factory=list,
        description="Substrings the suggested fix must contain; empty skips the fix scorer",
    )
    expected_citations: list[str] = Field(default_factory=list)
    confidence_floor: float = Field(default=0.0, ge=0.0, le=1.0)
    injection: bool = False
    injection_vector: str | None = Field(
        default=None, description="Where the payload rides: task_log, dag_source, task_note"
    )
    #: "authored" by us, or "human" from a dashboard thumb.
    source: Literal["authored", "human"] = "authored"
    notes: str | None = None


@dataclass(frozen=True)
class EvalCase:
    """One fixture plus its label."""

    case_id: str
    suite: str
    fixture: Path
    label_path: Path
    label: Label

    @property
    def is_injection(self) -> bool:
        return self.label.injection


def load_label(path: Path) -> Label:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Label.model_validate(raw)


def label_path_for(fixture: Path) -> Path:
    """The sibling label file for a fixture: same stem, ``.label.yaml``."""
    return fixture.parent / (fixture.stem + LABEL_SUFFIX)


def discover_cases(
    *,
    golden_dir: Path | str = GOLDEN_DIR,
    injection_dir: Path | str = INJECTION_DIR,
) -> list[EvalCase]:
    """Collect every labeled case, sorted for a stable report order.

    Raises:
        UnlabeledFixtureError: a fixture in either directory has no label.
    """
    cases: list[EvalCase] = []
    for suite, directory in (("golden", Path(golden_dir)), ("injection", Path(injection_dir))):
        if not directory.exists():
            continue
        for fixture in sorted(directory.glob("*.json")):
            label_file = label_path_for(fixture)
            if not label_file.exists():
                raise UnlabeledFixtureError(
                    f"{fixture} has no {label_file.name}. Every eval case needs a label; "
                    "write one or move the fixture out of the golden set."
                )
            cases.append(
                EvalCase(
                    case_id=f"{suite}/{fixture.stem}",
                    suite=suite,
                    fixture=fixture,
                    label_path=label_file,
                    label=load_label(label_file),
                )
            )
    if not cases:
        raise UnlabeledFixtureError("no eval cases found; the golden set is empty")
    return cases


def filter_cases(cases: list[EvalCase], label: str | None) -> list[EvalCase]:
    """Select a subset by suite name, taxonomy category, or ``injection``."""
    if not label:
        return cases
    wanted = label.strip().lower()
    if wanted == "injection":
        return [case for case in cases if case.is_injection]
    return [case for case in cases if case.suite == wanted or case.label.root_cause.value == wanted]


def labeled_dag_ids(cases: list[EvalCase]) -> set[str]:
    """DAG ids covered by the golden set, for the 'every broken DAG is labeled' check."""
    import json

    ids: set[str] = set()
    for case in cases:
        payload = json.loads(case.fixture.read_text(encoding="utf-8"))
        ids.add(payload["task_instance"]["dag_id"])
    return ids
