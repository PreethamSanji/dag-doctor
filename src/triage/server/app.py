"""The dashboard API.

A thin read layer over artifacts that already exist - stored cards, the latest
eval report, the Prometheus registry - plus one write: feedback, which lands in
``evals/golden/`` as a labeled case.

The API does not triage. Running the agent from an HTTP request would put an
unbounded, paid, multi-step loop behind a web handler; ``triage run`` owns that,
and the dashboard reads what it produced.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, Field

from triage.card.schema import TAXONOMY
from triage.metrics import REGISTRY
from triage.metrics import record_feedback as count_feedback
from triage.server.cards import CARDS_DIR, CardStore
from triage.server.feedback import FEEDBACK_DIR, FeedbackError, record_feedback

LATEST_REPORT = Path("evals/reports/latest/report.json")


class FeedbackRequest(BaseModel):
    """A dashboard thumb. A correction has to name the right answer."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["up", "down"]
    root_cause: str | None = Field(
        default=None, description="Correct category; required for a thumbs-down"
    )
    expected_fix: str | None = None
    notes: str | None = Field(default=None, max_length=2000)


def create_app(
    *,
    cards_dir: Path | str = CARDS_DIR,
    feedback_dir: Path | str = FEEDBACK_DIR,
    report_path: Path | str = LATEST_REPORT,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Build the API. Paths are injected so tests never touch the real store."""
    store = CardStore(cards_dir)
    app = FastAPI(title="dag-doctor", version="0.3.0")

    # The dashboard is served by Vite on another port in development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["http://localhost:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "cards": store.count(), "taxonomy": list(TAXONOMY)}

    @app.get("/api/cards")
    def list_cards(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict[str, Any]:
        """Recent runs, newest first. Summaries only - no incident content."""
        return {"cards": [stored.summary() for stored in store.list(limit)]}

    @app.get("/api/cards/{card_id}")
    def get_card(card_id: str) -> dict[str, Any]:
        """One full card: verdict, citations, evidence trail, security flags."""
        try:
            stored = store.get(card_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="card not found") from exc
        return {
            "card_id": stored.card_id,
            "created_at": stored.created_at.isoformat(),
            "card": stored.card.model_dump(mode="json"),
        }

    @app.post("/api/cards/{card_id}/feedback")
    def post_feedback(card_id: str, request: Annotated[FeedbackRequest, Body()]) -> dict[str, Any]:
        """Promote a thumb into a golden-set case with ``source: human``."""
        try:
            stored = store.get(card_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="card not found") from exc

        try:
            written = record_feedback(
                stored,
                verdict=request.verdict,
                root_cause=request.root_cause,
                expected_fix=request.expected_fix,
                notes=request.notes,
                out_dir=feedback_dir,
            )
        except FeedbackError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        count_feedback(request.verdict)
        return {
            "case_id": written.case_id,
            "root_cause": written.root_cause,
            "fixture": str(written.fixture),
            "label": str(written.label_path),
        }

    @app.get("/api/eval/latest")
    def latest_eval() -> dict[str, Any]:
        """The most recent eval report, or an empty shape before the first run."""
        path = Path(report_path)
        if not path.exists():
            return {"available": False}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {"available": True, **payload}

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    return app
