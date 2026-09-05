import { useCallback, useEffect, useState } from "react";

import { getCard, getLatestEval, listCards } from "./api";
import { CardView } from "./components/CardDetail";
import { CardList } from "./components/CardList";
import { EvalPanel } from "./components/EvalPanel";
import { FeedbackForm } from "./components/FeedbackForm";
import type { CardDetail, CardSummary, EvalReport } from "./types";

export function App() {
  const [cards, setCards] = useState<CardSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<CardDetail | null>(null);
  const [report, setReport] = useState<EvalReport>({ available: false });
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [loaded, latest] = await Promise.all([listCards(), getLatestEval()]);
      setCards(loaded);
      setReport(latest);
      setError(null);
      // Keep selection on refresh; else default to newest.
      setSelected((current) =>
        current && loaded.some((card) => card.card_id === current)
          ? current
          : (loaded[0]?.card_id ?? null),
      );
    } catch (caught) {
      setError((caught as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    getCard(selected)
      .then(setDetail)
      .catch((caught: Error) => setError(caught.message));
  }, [selected]);

  return (
    <div className="app">
      <header className="masthead">
        <h1>dag-doctor</h1>
        <span className="tag">Airflow incident triage</span>
        <span style={{ marginLeft: "auto" }}>
          <button onClick={() => void refresh()}>Refresh</button>
        </span>
      </header>

      {error && <p className="notice bad">{error}</p>}

      <div className="columns">
        <div>
          <section className="panel">
            <h2>Recent triage ({cards.length})</h2>
            <CardList cards={cards} selected={selected} onSelect={setSelected} />
          </section>

          <section className="panel">
            <h2>Eval gate</h2>
            <EvalPanel report={report} />
          </section>
        </div>

        <div>
          {detail ? (
            <>
              <CardView detail={detail} />
              <section className="panel">
                <h2>Feedback</h2>
                <p className="muted" style={{ marginTop: 0 }}>
                  A thumb writes a labeled case into the golden set. Feedback is data: it is
                  scored by the same harness as an authored label.
                </p>
                <FeedbackForm key={detail.card_id} detail={detail} />
              </section>
            </>
          ) : (
            <section className="panel">
              <p className="empty">Select a card to see its verdict, citations, and trail.</p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
