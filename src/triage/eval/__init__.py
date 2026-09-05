"""Eval harness: golden set, scorers, threshold gate, report writer.

The eval gate is a regression gate, not a demo. Anything touching prompts, tool
descriptions, retrieval, chunking, the model, or loop logic has to pass a full
run of this suite before it lands - and the way to fix a failing eval is to fix
the change, never to weaken a scorer or quietly lower a bound in
``evals/thresholds.yaml``.
"""

from triage.eval.gate import Check, GateResult, Threshold, evaluate, load_thresholds
from triage.eval.harness import CaseRun, EvalRun, run_case, run_suite
from triage.eval.labels import (
    EvalCase,
    Label,
    UnlabeledFixtureError,
    discover_cases,
    filter_cases,
)
from triage.eval.report import build_payload, render_markdown, write_report
from triage.eval.scorers import ScoredCase, aggregate, confusion, score_case

__all__ = [
    "CaseRun",
    "Check",
    "EvalCase",
    "EvalRun",
    "GateResult",
    "Label",
    "ScoredCase",
    "Threshold",
    "UnlabeledFixtureError",
    "aggregate",
    "build_payload",
    "confusion",
    "discover_cases",
    "evaluate",
    "filter_cases",
    "load_thresholds",
    "render_markdown",
    "run_case",
    "run_suite",
    "score_case",
    "write_report",
]
