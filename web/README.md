# web — the triage dashboard

A React + TypeScript view over the cards `triage run` produces and the reports
`triage eval` writes. Two jobs:

- **Review a verdict.** Root cause, confidence, citations with their quotes, and
  the full evidence trail — what the loop called, with what arguments, and what
  came back. Security flags are on the list row, so a poisoned incident is
  visible before anyone opens it.
- **Correct one.** A thumb writes a labeled case into `evals/golden/` with
  `source: human`. Feedback is data: it is scored by the same harness, gated by
  the same thresholds, and reviewed in the same diff as an authored label. A
  thumbs-down has to name the correct category — feedback that only says "wrong"
  cannot be scored against, and the API rejects it.

## Running it

```bash
uv run triage serve       # API on :8000
cd web && npm run dev     # dashboard on :5173, /api proxied to the API
```

`npm run build` typechecks with `tsc -b` before bundling, and CI runs it.

## Layout

```
src/
  api.ts                fetch wrappers; errors surface FastAPI's `detail`
  types.ts              mirrors src/triage/card/schema.py
  App.tsx               list + detail + eval panel
  components/
    CardList.tsx        recent runs, with flags
    CardDetail.tsx      verdict, citations, evidence trail
    EvalPanel.tsx       the latest report and the gate's verdict
    FeedbackForm.tsx    thumbs → golden-set case
```

`types.ts` mirrors the card schema, which lives in `src/triage/card/schema.py`
and is the single source of truth. When the schema changes, this file changes in
the same commit.
