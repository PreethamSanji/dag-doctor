import { useState } from "react";

import { sendFeedback } from "../api";
import { TAXONOMY, type CardDetail } from "../types";

/**
 * A thumb writes a labeled case into `evals/golden/` with `source: human`, so
 * feedback is scored by the same harness as an authored label.
 *
 * A thumbs-down has to name the correct category: feedback that only says
 * "wrong" cannot be scored against, and the API rejects it.
 */
export function FeedbackForm({ detail }: { detail: CardDetail }) {
  const [verdict, setVerdict] = useState<"up" | "down">("up");
  const [rootCause, setRootCause] = useState<string>(detail.card.root_cause.category);
  const [expectedFix, setExpectedFix] = useState("");
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState<{ ok: boolean; message: string } | null>(null);
  const [sending, setSending] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSending(true);
    setStatus(null);
    try {
      const written = await sendFeedback(detail.card_id, {
        verdict,
        root_cause: verdict === "down" ? rootCause : undefined,
        expected_fix: expectedFix.trim() || undefined,
        notes: notes.trim() || undefined,
      });
      setStatus({ ok: true, message: `Wrote ${written.label} as ${written.root_cause}.` });
      setExpectedFix("");
      setNotes("");
    } catch (error) {
      setStatus({ ok: false, message: (error as Error).message });
    } finally {
      setSending(false);
    }
  }

  return (
    <form className="feedback" onSubmit={submit}>
      <div className="row">
        <button
          type="button"
          className={verdict === "up" ? "chip ok" : ""}
          onClick={() => setVerdict("up")}
          aria-pressed={verdict === "up"}
        >
          Correct
        </button>
        <button
          type="button"
          className={verdict === "down" ? "chip bad" : ""}
          onClick={() => setVerdict("down")}
          aria-pressed={verdict === "down"}
        >
          Wrong
        </button>
      </div>

      {verdict === "down" && (
        <label>
          Correct root cause
          <select value={rootCause} onChange={(event) => setRootCause(event.target.value)}>
            {TAXONOMY.map((category) => (
              <option key={category} value={category}>
                {category}
              </option>
            ))}
          </select>
        </label>
      )}

      <label>
        Expected fix {verdict === "up" && <span>(defaults to the card&apos;s fix)</span>}
        <input
          value={expectedFix}
          onChange={(event) => setExpectedFix(event.target.value)}
          placeholder={detail.card.suggested_fix}
        />
      </label>

      <label>
        Notes
        <textarea rows={2} value={notes} onChange={(event) => setNotes(event.target.value)} />
      </label>

      <div className="row">
        <button type="submit" disabled={sending}>
          {sending ? "Saving…" : "Save as golden-set case"}
        </button>
        <span className="muted">source: human</span>
      </div>

      {status && (
        <p className={`notice ${status.ok ? "ok" : "bad"}`}>
          <span className="mono">{status.message}</span>
        </p>
      )}
    </form>
  );
}
