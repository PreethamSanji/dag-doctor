"""The golden-set rules, enforced as tests.

These are the checks that make "no label, no eval case" mechanical rather than
aspirational: CI fails on an unlabeled fixture, and on a broken DAG that no
labeled case covers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from triage.card.schema import TAXONOMY
from triage.eval.labels import (
    UnlabeledFixtureError,
    discover_cases,
    filter_cases,
    labeled_dag_ids,
    load_label,
)

BROKEN_DAGS = Path("broken_dags")


@pytest.fixture(scope="module")
def cases():
    return discover_cases()


def test_every_fixture_has_a_label(cases):
    assert cases
    for case in cases:
        assert case.label_path.exists()
        assert case.label.root_cause.value in TAXONOMY


def test_unlabeled_fixture_is_an_error(tmp_path):
    (tmp_path / "orphan.json").write_text("{}", encoding="utf-8")
    with pytest.raises(UnlabeledFixtureError, match="orphan.label.yaml"):
        discover_cases(golden_dir=tmp_path, injection_dir=tmp_path / "none")


def test_every_broken_dag_is_covered(cases):
    """A new broken DAG without a labeled case fails CI."""
    authored = {path.stem for path in BROKEN_DAGS.glob("*.py") if not path.name.startswith("_")}
    covered = labeled_dag_ids(cases)
    assert authored <= covered, f"unlabeled broken DAGs: {sorted(authored - covered)}"


def test_taxonomy_is_fully_covered(cases):
    """Every class in the closed taxonomy has at least one golden case."""
    labeled = {case.label.root_cause.value for case in cases}
    assert set(TAXONOMY) == labeled


def test_injection_cases_label_the_real_failure(cases):
    """The poison is the payload; the label is the failure underneath."""
    injection = [case for case in cases if case.is_injection]
    assert injection
    for case in injection:
        assert case.suite == "injection"
        assert case.label.injection_vector
        payload = json.loads(case.fixture.read_text(encoding="utf-8"))
        assert payload["task_instance"]["state"] == "failed"


def test_filter_by_suite_category_and_injection(cases):
    assert filter_cases(cases, None) == cases
    assert all(case.is_injection for case in filter_cases(cases, "injection"))
    assert all(case.suite == "golden" for case in filter_cases(cases, "golden"))
    by_category = filter_cases(cases, "config_error")
    assert by_category and all(
        case.label.root_cause.value == "config_error" for case in by_category
    )


def test_label_rejects_an_unknown_category(tmp_path):
    path = tmp_path / "x.label.yaml"
    path.write_text("root_cause: vibes\nexpected_fix: none\n", encoding="utf-8")
    with pytest.raises(ValueError, match="root_cause"):
        load_label(path)
