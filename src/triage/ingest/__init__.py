"""Ingestion: Airflow REST client, deploy history, incident assembly."""

from triage.ingest.airflow_client import AirflowClient, AirflowError
from triage.ingest.deploys import recent_deploys
from triage.ingest.incident import (
    incident_key,
    ingest_incident,
    load_fixture,
    save_fixture,
)
from triage.ingest.models import (
    DagSource,
    DeployEvent,
    Incident,
    TaskInstance,
    TaskLog,
    TaskRunSummary,
)

__all__ = [
    "AirflowClient",
    "AirflowError",
    "DagSource",
    "DeployEvent",
    "Incident",
    "TaskInstance",
    "TaskLog",
    "TaskRunSummary",
    "incident_key",
    "ingest_incident",
    "load_fixture",
    "recent_deploys",
    "save_fixture",
]
