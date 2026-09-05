# evals — the regression gate

Triage quality is measured, not asserted. Every change to a prompt, a tool
description, retrieval, chunking, the model, or the loop has to pass a full run
of this suite before it lands.

```
golden/           incident fixtures + labels, one per taxonomy class
injection/        adversarial fixtures; the label is the real failure underneath
thresholds.yaml   the gate — the single source of truth for pass/fail
reports/          run artifacts (gitignored)
```

## The rule

**No label, no eval case.** Every fixture needs a sibling `<stem>.label.yaml`.
`triage eval` refuses to run when one is missing, and `make check` fails on an
unlabeled fixture or on a broken DAG that no case covers — so the golden set is
CI-enforced rather than aspirational.

```yaml
root_cause: config_error          # from the closed taxonomy
expected_fix: "Define the s3_bucket Airflow Variable"
fix_keywords: [s3_bucket, variable]   # substrings the fix must contain
expected_citations:                   # prefix-matched against source and chunk id
  - corpus/helm/values.yaml
confidence_floor: 0.6
injection: false
source: authored                  # or `human`, written back from a dashboard thumb
```

## Running it

```bash
uv run triage eval                    # full set, writes a report, applies the gate
uv run triage eval --fast             # random subset; reports, does not gate
uv run triage eval --label injection  # adversarial cases only
uv run triage eval --label config_error
```

A partial run never gates. `--fast` and `--label` are for iteration; only the
full golden set can say a change is safe.

## Metrics

| metric | what it measures |
| --- | --- |
| `root_cause_accuracy` | verdict matches the label, over the closed 7-class taxonomy |
| `injection_resistance` | on adversarial cases: verdict matches ground truth **and** the payload was flagged |
| `citation_groundedness` | share of cards carrying a citation that resolved to a chunk actually in context |
| `citation_precision` | share of cards citing a source the label expects |
| `hallucination_rate` | share of cards where a proposed citation resolved to nothing |
| `fix_match` | the suggested fix names what the real fix has to name |
| `confidence_floor_pass` | correct verdicts that also cleared the label's floor |
| `parse_error_rate` | structured output failed twice and produced a parse-error card |
| `p95_latency_ms`, `mean_cost_usd` | budget guards |

A metric with no measurable cases is skipped, not failed.

## Adversarial fixtures

The poison is the payload; the label is the answer. Each `injection/` case
carries the real failure as its `root_cause`, so "resisted injection" is scored
against ground truth rather than against how reassuring the card sounds. The
three vectors currently covered — `injection_vector` in each label — are the
task log, the DAG source, and the operator-supplied task note.

Widening or narrowing the sanitizer is a security change: it needs this subset,
the full suite, and a new adversarial fixture when the change widens behavior.

## Thresholds

`thresholds.yaml` is the only place pass/fail lives. Never make a red run green
by lowering a bound or weakening a scorer — a threshold change is explicit,
reviewed, and justified in the commit that moves it.
