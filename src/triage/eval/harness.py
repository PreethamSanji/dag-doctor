"""Running the golden set.

The harness replays frozen incidents through the *real* triage path - the same
loop, tools, sanitizer, and card assembly the CLI uses - and scores the cards it
gets back. Only the incident is frozen; nothing about the agent is stubbed, or
the eval would measure the stub.

The model client is injected rather than constructed here, which is what lets
tests exercise the whole harness against recorded transcripts offline.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from triage.agent.loop import run_agent
from triage.agent.single_shot import run_single_shot
from triage.card.schema import RootCause, RootCauseCategory, RunMetadata, TriageCard
from triage.config import Config
from triage.eval.labels import EvalCase
from triage.eval.scorers import ScoredCase, aggregate, confusion, score_case
from triage.ingest.incident import incident_key, load_fixture
from triage.llm import LLMClient
from triage.retrieval.retriever import Retriever

#: Builds a fresh client per case, so concurrent cases never share request state.
ClientFactory = Callable[[], LLMClient]


@dataclass
class CaseRun:
    """One case's card and score, kept together for the report."""

    case: EvalCase
    card: TriageCard
    scored: ScoredCase


@dataclass
class EvalRun:
    """Everything one eval invocation produced."""

    runs: list[CaseRun]
    metrics: dict[str, float | None] = field(default_factory=dict)
    total_cases: int = 0

    @property
    def full_run(self) -> bool:
        """True when every labeled case in the suite actually ran."""
        return len(self.runs) == self.total_cases

    @property
    def scored(self) -> list[ScoredCase]:
        return [run.scored for run in self.runs]

    @property
    def confusion(self) -> dict[str, dict[str, int]]:
        return confusion(self.scored)


def run_case(
    case: EvalCase,
    *,
    config: Config,
    client: LLMClient,
    retriever: Retriever | None,
) -> TriageCard:
    """Triage one fixture through the configured mode."""
    incident = load_fixture(case.fixture)
    if config.agent.mode == "single_shot":
        return run_single_shot(incident, config=config, client=client, retriever=retriever)
    return run_agent(incident, config=config, client=client, retriever=retriever)


def _error_card(case: EvalCase, error: Exception, config: Config, elapsed_ms: int) -> TriageCard:
    """A case that crashed is a failed case, not a lost run.

    It still produces a row - with ``parse_error`` set - so the report shows what
    broke instead of silently shrinking the denominator.
    """
    incident = load_fixture(case.fixture)
    return TriageCard(
        incident=incident_key(incident),
        root_cause=RootCause(
            category=RootCauseCategory.PLATFORM_ERROR,
            hypothesis="Triage raised before producing a verdict.",
            confidence=0.0,
        ),
        suggested_fix="Inspect the harness error and re-run this case.",
        insufficient_evidence=True,
        parse_error=f"{type(error).__name__}: {error}"[:2000],
        run=RunMetadata(
            model=config.agent.model,
            mode=config.agent.mode,
            max_steps=config.agent.max_steps,
            latency_ms=elapsed_ms,
            config_fingerprint=config.fingerprint,
        ),
    )


def run_suite(
    cases: Sequence[EvalCase],
    *,
    config: Config,
    client_factory: ClientFactory,
    retriever: Retriever | None = None,
    total_cases: int | None = None,
    workers: int = 4,
    on_case: Callable[[CaseRun], None] | None = None,
) -> EvalRun:
    """Score every case, optionally in parallel.

    Args:
        cases: the cases to run (already filtered by ``--fast`` or ``--label``).
        config: the config whose fingerprint the report records.
        client_factory: builds one model client per case.
        retriever: shared retrieval index; ``None`` disables ``query_runbook``.
        total_cases: size of the unfiltered suite, which decides whether the
            gate is enforced. Defaults to ``len(cases)``.
        workers: concurrent cases. Use 1 for a stable ordering while debugging.
        on_case: called as each case finishes, for progress output.
    """

    def execute(case: EvalCase) -> CaseRun:
        started = time.perf_counter()
        try:
            card = run_case(case, config=config, client=client_factory(), retriever=retriever)
        except Exception as exc:  # a broken case must still produce a row
            elapsed = int((time.perf_counter() - started) * 1000)
            card = _error_card(case, exc, config, elapsed)
        result = CaseRun(case=case, card=card, scored=score_case(card, case))
        if on_case is not None:
            on_case(result)
        return result

    if workers <= 1:
        runs = [execute(case) for case in cases]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            runs = list(pool.map(execute, cases))

    runs.sort(key=lambda run: run.case.case_id)
    return EvalRun(
        runs=runs,
        metrics=aggregate([run.scored for run in runs]),
        total_cases=total_cases if total_cases is not None else len(cases),
    )
