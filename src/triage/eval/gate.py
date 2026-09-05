"""The threshold gate.

``evals/thresholds.yaml`` is the single source of truth for pass/fail. Numbers
live there rather than in code or in prose so that raising or lowering one shows
up in a diff and has to be justified in review.

Two rules keep the gate honest:

* A metric with no measurable cases is **skipped**, not failed - a filtered run
  should report, not manufacture a red build.
* A partial run (``--fast``, ``--label``) does not gate at all. Only the full
  golden set can say "this change is safe"; see :func:`evaluate`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

THRESHOLDS_PATH = Path("evals/thresholds.yaml")


@dataclass(frozen=True)
class Threshold:
    metric: str
    bound: float
    kind: str  # "min" or "max"

    def holds(self, value: float) -> bool:
        return value >= self.bound if self.kind == "min" else value <= self.bound

    def describe(self) -> str:
        return f"{self.metric} {'>=' if self.kind == 'min' else '<='} {self.bound:g}"


@dataclass(frozen=True)
class Check:
    threshold: Threshold
    value: float | None

    @property
    def skipped(self) -> bool:
        return self.value is None

    @property
    def passed(self) -> bool:
        return self.skipped or self.threshold.holds(self.value)  # type: ignore[arg-type]


@dataclass
class GateResult:
    checks: list[Check]
    enforced: bool
    reason: str = ""

    @property
    def failures(self) -> list[Check]:
        return [check for check in self.checks if not check.passed]

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def exit_code(self) -> int:
        """Non-zero only when the gate is enforced and something failed."""
        return 1 if self.enforced and not self.passed else 0


def load_thresholds(path: Path | str = THRESHOLDS_PATH) -> list[Threshold]:
    """Read the gate. A missing or malformed file is an error, not a free pass."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    metrics = raw.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError(f"{path}: expected a non-empty 'metrics' mapping")

    thresholds: list[Threshold] = []
    for metric, spec in metrics.items():
        if not isinstance(spec, dict) or not ({"min", "max"} & spec.keys()):
            raise ValueError(f"{path}: {metric} needs a 'min' or 'max' bound")
        for kind in ("min", "max"):
            if kind in spec:
                thresholds.append(Threshold(metric=metric, bound=float(spec[kind]), kind=kind))
    return thresholds


def evaluate(
    metrics: dict[str, float | None],
    thresholds: list[Threshold],
    *,
    full_run: bool,
) -> GateResult:
    """Check metrics against thresholds.

    Args:
        metrics: aggregated metrics from :func:`triage.eval.scorers.aggregate`.
        thresholds: the parsed contents of ``evals/thresholds.yaml``.
        full_run: whether every labeled case ran. Only a full run gates.
    """
    checks = [
        Check(threshold=threshold, value=metrics.get(threshold.metric)) for threshold in thresholds
    ]
    reason = "" if full_run else "partial run: reporting only, the gate needs the full golden set"
    return GateResult(checks=checks, enforced=full_run, reason=reason)
