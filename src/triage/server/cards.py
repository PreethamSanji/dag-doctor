"""Persisting triage cards so the dashboard has something to show.

A card is stored with the incident that produced it. That pairing is what makes
feedback useful: a thumb on a card can be promoted into a golden-set case only
if the exact incident it was judged on is still on disk.

The store is a directory of JSON files. It is deliberately not a database - the
system of record for evaluation is ``evals/``, and this is a rolling buffer of
recent runs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from triage.card.schema import TriageCard
from triage.ingest.models import Incident

CARDS_DIR = Path(".triage/cards")
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _slug(value: str, limit: int = 48) -> str:
    return _UNSAFE.sub("-", value).strip("-")[:limit] or "unknown"


@dataclass(frozen=True)
class StoredCard:
    """One persisted run."""

    card_id: str
    created_at: datetime
    card: TriageCard
    incident: Incident

    def summary(self) -> dict:
        """The list-view projection: enough to render a row, no incident content."""
        return {
            "card_id": self.card_id,
            "created_at": self.created_at.isoformat(),
            "incident": str(self.card.incident),
            "dag_id": self.card.incident.dag_id,
            "task_id": self.card.incident.task_id,
            "category": self.card.root_cause.category.value,
            "confidence": self.card.root_cause.confidence,
            "hypothesis": self.card.root_cause.hypothesis,
            "security_flags": self.card.security_flags,
            "insufficient_evidence": self.card.insufficient_evidence,
            "parse_error": self.card.parse_error is not None,
            "citations": len(self.card.citations),
            "steps_used": self.card.run.steps_used,
            "latency_ms": self.card.run.latency_ms,
            "cost_usd": self.card.run.cost_usd,
            "model": self.card.run.model,
        }


class CardStore:
    """Read and write triage cards on disk, newest first."""

    def __init__(self, root: Path | str = CARDS_DIR) -> None:
        self.root = Path(root)

    def _path(self, card_id: str) -> Path:
        # Card ids come from URLs; refuse anything that could escape the store.
        if card_id != _slug(card_id, limit=128):
            raise KeyError(card_id)
        return self.root / f"{card_id}.json"

    def save(self, card: TriageCard, incident: Incident) -> str:
        """Persist one card with its incident. Returns the new card id."""
        created = datetime.now(UTC)
        card_id = (
            f"{created.strftime('%Y%m%dT%H%M%S%fZ')}-"
            f"{_slug(card.incident.dag_id)}-{_slug(card.incident.task_id, 24)}"
        )
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "card_id": card_id,
            "created_at": created.isoformat(),
            "card": card.model_dump(mode="json"),
            "incident": incident.model_dump(mode="json"),
        }
        self._path(card_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return card_id

    def get(self, card_id: str) -> StoredCard:
        """Load one stored run.

        Raises:
            KeyError: no such card.
        """
        path = self._path(card_id)
        if not path.exists():
            raise KeyError(card_id)
        return _parse(json.loads(path.read_text(encoding="utf-8")))

    def list(self, limit: int = 50) -> list[StoredCard]:
        """The most recent runs. Card ids sort chronologically, so name order is enough."""
        if not self.root.exists():
            return []
        paths = sorted(self.root.glob("*.json"), reverse=True)[:limit]
        stored: list[StoredCard] = []
        for path in paths:
            try:
                stored.append(_parse(json.loads(path.read_text(encoding="utf-8"))))
            except (ValueError, KeyError):
                continue  # a half-written or outdated file is not worth failing a list on
        return stored

    def count(self) -> int:
        return len(list(self.root.glob("*.json"))) if self.root.exists() else 0


def _parse(payload: dict) -> StoredCard:
    return StoredCard(
        card_id=payload["card_id"],
        created_at=datetime.fromisoformat(payload["created_at"]),
        card=TriageCard.model_validate(payload["card"]),
        incident=Incident.model_validate(payload["incident"]),
    )
