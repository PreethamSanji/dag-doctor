"""The dashboard's backend: card store, feedback write-back, and the API.

Reads what ``triage run`` and ``triage eval`` already produced; the one thing it
writes is feedback, and it writes it as a labeled eval case rather than as a
private thumbs table.
"""

from triage.server.app import create_app
from triage.server.cards import CardStore, StoredCard
from triage.server.feedback import FeedbackError, WrittenCase, record_feedback

__all__ = [
    "CardStore",
    "FeedbackError",
    "StoredCard",
    "WrittenCase",
    "create_app",
    "record_feedback",
]
