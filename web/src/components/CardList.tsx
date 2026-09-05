import type { CardSummary } from "../types";

interface Props {
  cards: CardSummary[];
  selected: string | null;
  onSelect: (cardId: string) => void;
}

/** Recent runs. Flags are surfaced here so a poisoned incident is visible
 *  before anyone opens the card. */
export function CardList({ cards, selected, onSelect }: Props) {
  if (cards.length === 0) {
    return (
      <p className="empty">
        No triage cards yet. Run <code className="mono">triage run</code> and reload.
      </p>
    );
  }

  return (
    <div className="card-list">
      {cards.map((card) => (
        <button
          key={card.card_id}
          className={`card-row${card.card_id === selected ? " selected" : ""}`}
          onClick={() => onSelect(card.card_id)}
        >
          <span className="title">
            {card.dag_id}/{card.task_id}
          </span>
          <span className="row">
            <span className="chip category">{card.category}</span>
            <span className="muted mono">{card.confidence.toFixed(2)}</span>
            {card.security_flags.includes("injection_detected") && (
              <span className="chip bad">injection</span>
            )}
            {card.insufficient_evidence && <span className="chip warn">low evidence</span>}
            {card.parse_error && <span className="chip bad">parse error</span>}
          </span>
          <span className="muted mono">{new Date(card.created_at).toLocaleString()}</span>
        </button>
      ))}
    </div>
  );
}
