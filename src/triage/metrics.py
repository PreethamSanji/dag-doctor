"""Prometheus instrumentation for the agent.

What is worth alerting on here is not request rate but triage quality and cost:
how often a run exhausts its step budget, how often structured output fails, how
often incident content trips the injection detector, and what a triage costs.
Those are the same properties the eval gate scores, exported live.

Everything is registered against a module-level registry that the API serves at
``/metrics``. Instrumentation is deliberately passive - :func:`record_card` reads
a finished card - so no metric can change what the agent does.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram

from triage.card.schema import TriageCard

REGISTRY = CollectorRegistry()

TRIAGE_RUNS = Counter(
    "triage_runs_total",
    "Triage runs, by mode and root-cause category.",
    ["mode", "category"],
    registry=REGISTRY,
)
TRIAGE_LATENCY = Histogram(
    "triage_latency_seconds",
    "Wall-clock latency of one triage run, tool steps included.",
    ["mode"],
    buckets=(1, 2.5, 5, 10, 20, 30, 60, 120, 300),
    registry=REGISTRY,
)
TRIAGE_COST = Histogram(
    "triage_cost_usd",
    "Model cost of one triage run.",
    ["mode"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
    registry=REGISTRY,
)
TRIAGE_STEPS = Histogram(
    "triage_steps_used",
    "Tool-calling steps spent before the verdict.",
    ["mode"],
    buckets=(0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16),
    registry=REGISTRY,
)
TOOL_CALLS = Counter(
    "triage_tool_calls_total",
    "Tool calls made by the agent, by tool and outcome.",
    ["tool", "outcome"],
    registry=REGISTRY,
)
SECURITY_FLAGS = Counter(
    "triage_security_flags_total",
    "Security flags raised on triage cards, by flag.",
    ["flag"],
    registry=REGISTRY,
)
PARSE_ERRORS = Counter(
    "triage_parse_errors_total",
    "Verdicts that failed schema validation after their structured retry.",
    ["mode"],
    registry=REGISTRY,
)
INSUFFICIENT_EVIDENCE = Counter(
    "triage_insufficient_evidence_total",
    "Verdicts emitted without enough evidence, including step-budget exhaustion.",
    ["mode"],
    registry=REGISTRY,
)
FEEDBACK = Counter(
    "triage_feedback_total",
    "Dashboard feedback received, by verdict.",
    ["verdict"],
    registry=REGISTRY,
)


def record_card(card: TriageCard) -> None:
    """Export one finished card. Never raises: metrics must not break triage."""
    mode = card.run.mode
    try:
        TRIAGE_RUNS.labels(mode=mode, category=card.root_cause.category.value).inc()
        TRIAGE_LATENCY.labels(mode=mode).observe(card.run.latency_ms / 1000)
        TRIAGE_COST.labels(mode=mode).observe(card.run.cost_usd)
        TRIAGE_STEPS.labels(mode=mode).observe(card.run.steps_used)

        for step in card.evidence_trail:
            TOOL_CALLS.labels(tool=step.tool, outcome="error" if step.error else "ok").inc()
        for flag in card.security_flags:
            SECURITY_FLAGS.labels(flag=flag).inc()
        if card.parse_error is not None:
            PARSE_ERRORS.labels(mode=mode).inc()
        if card.insufficient_evidence:
            INSUFFICIENT_EVIDENCE.labels(mode=mode).inc()
    except Exception:  # pragma: no cover - instrumentation is never load-bearing
        pass


def record_feedback(verdict: str) -> None:
    """Count one dashboard thumb."""
    FEEDBACK.labels(verdict=verdict).inc()
