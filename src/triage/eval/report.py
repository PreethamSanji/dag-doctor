"""Eval report artifacts.

Every run writes a JSON report (machine-readable, what CI diffs) and a Markdown
summary (what a human reads in a PR). Both record the config fingerprint, so a
metric delta can always be attributed to a specific model, effort, ``max_steps``
and retrieval ``k``.

Reports are gitignored and deliberately quote-free at the case level: a report
that embedded log content would be a log-content leak in an artifact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from triage.config import Config
from triage.eval.gate import GateResult
from triage.eval.harness import EvalRun

REPORTS_DIR = Path("evals/reports")

#: Metrics shown first in the Markdown summary, in the order they matter.
HEADLINE = (
    "root_cause_accuracy",
    "injection_resistance",
    "citation_groundedness",
    "citation_precision",
    "hallucination_rate",
    "fix_match",
    "confidence_floor_pass",
    "parse_error_rate",
    "p95_latency_ms",
    "mean_cost_usd",
)


@dataclass(frozen=True)
class Report:
    path: Path
    json_path: Path
    markdown_path: Path


def _fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 1000 or value == int(value):
        return f"{value:,.0f}"
    return f"{value:.3f}"


def build_payload(
    run: EvalRun,
    gate: GateResult,
    config: Config,
    *,
    label: str | None = None,
    fast: bool = False,
) -> dict:
    """The JSON report. Case rows carry scores and ids, never log text."""
    return {
        "schema_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "config_fingerprint": config.fingerprint,
        "selection": {"label": label, "fast": fast, "full_run": run.full_run},
        "metrics": run.metrics,
        "confusion": run.confusion,
        "gate": {
            "enforced": gate.enforced,
            "passed": gate.passed,
            "reason": gate.reason,
            "checks": [
                {
                    "metric": check.threshold.metric,
                    "bound": check.threshold.bound,
                    "kind": check.threshold.kind,
                    "value": check.value,
                    "passed": check.passed,
                    "skipped": check.skipped,
                }
                for check in gate.checks
            ],
        },
        "cases": [scored.as_row() for scored in run.scored],
    }


def render_markdown(payload: dict) -> str:
    """The PR-readable summary."""
    metrics = payload["metrics"]
    gate = payload["gate"]
    status = "PASS" if gate["passed"] else "FAIL"
    if not gate["enforced"]:
        status = f"REPORT ONLY ({gate['reason']})"

    lines = [
        "# Eval report",
        "",
        f"- **Gate:** {status}",
        f"- **Cases:** {int(metrics.get('cases') or 0)}",
        f"- **Config:** `{json.dumps(payload['config_fingerprint'], sort_keys=True)}`",
        f"- **Run at:** {payload['created_at']}",
        "",
        "## Metrics",
        "",
        "| metric | value | threshold | result |",
        "| --- | --- | --- | --- |",
    ]

    bounds = {check["metric"]: check for check in gate["checks"]}
    ordered = [name for name in HEADLINE if name in metrics]
    ordered += [name for name in metrics if name not in ordered and name != "cases"]
    for name in ordered:
        check = bounds.get(name)
        threshold = (
            f"{'>=' if check['kind'] == 'min' else '<='} {check['bound']:g}" if check else "-"
        )
        if check is None:
            result = "-"
        elif check["skipped"]:
            result = "skipped"
        else:
            result = "pass" if check["passed"] else "**fail**"
        lines.append(f"| {name} | {_fmt(metrics[name])} | {threshold} | {result} |")

    lines += [
        "",
        "## Cases",
        "",
        "| case | expected | predicted | conf | cited | flags |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for case in payload["cases"]:
        mark = "ok" if case["correct"] else "**miss**"
        flags = ", ".join(case["security_flags"]) or "-"
        lines.append(
            f"| {case['case_id']} | {case['expected']} | {case['predicted']} {mark} "
            f"| {case['confidence']:.2f} | {'yes' if case['cited'] else 'no'} | {flags} |"
        )

    if payload["confusion"]:
        lines += ["", "## Confusion", "", "| expected | predicted (count) |", "| --- | --- |"]
        for expected, row in sorted(payload["confusion"].items()):
            cells = ", ".join(f"{pred}={count}" for pred, count in sorted(row.items()))
            lines.append(f"| {expected} | {cells} |")

    return "\n".join(lines) + "\n"


def write_report(
    run: EvalRun,
    gate: GateResult,
    config: Config,
    *,
    out_dir: Path | str = REPORTS_DIR,
    label: str | None = None,
    fast: bool = False,
) -> Report:
    """Write ``report.json`` and ``report.md`` under a timestamped directory.

    ``latest/`` is refreshed alongside it so CI and the dashboard have a stable
    path to read without globbing.
    """
    payload = build_payload(run, gate, config, label=label, fast=fast)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = Path(out_dir)
    target = root / stamp
    target.mkdir(parents=True, exist_ok=True)

    json_path = target / "report.json"
    markdown_path = target / "report.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")

    latest = root / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    (latest / "report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (latest / "report.md").write_text(render_markdown(payload), encoding="utf-8")

    return Report(path=target, json_path=json_path, markdown_path=markdown_path)
