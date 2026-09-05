"""Assembling one incident from a live Airflow, or from a recorded fixture.

Live ingestion is what makes the ground-truth trick work: we author the broken
DAGs, a real Airflow runs them, and the logs and metadata we capture are
genuine. Fixtures are those same captures, frozen to disk, so integration tests
and evals replay real incidents without network or an LLM.
"""

from __future__ import annotations

import json
from pathlib import Path

from triage.card.schema import IncidentKey
from triage.config import Config
from triage.ingest.airflow_client import AirflowClient, AirflowError
from triage.ingest.deploys import recent_deploys
from triage.ingest.models import Incident


def ingest_incident(
    client: AirflowClient,
    key: IncidentKey,
    config: Config,
    *,
    dags_dir: Path | str = "broken_dags",
) -> Incident:
    """Pull everything triage needs for one failed task instance.

    Optional sources degrade to empty rather than aborting the run: a missing
    DAG source or an inaccessible git history is a gap in the evidence, and the
    agent should report low confidence rather than crash.
    """
    task_instance = client.get_task_instance(key.dag_id, key.run_id, key.task_id)
    try_number = key.try_number or task_instance.try_number or 1
    log = client.get_log(key.dag_id, key.run_id, key.task_id, try_number)

    try:
        dag_source = client.get_dag_source(key.dag_id)
    except AirflowError:
        dag_source = None

    try:
        history = client.get_task_history(key.dag_id, key.task_id, limit=config.ingest.history_runs)
    except AirflowError:
        history = []

    try:
        import_errors = client.get_import_errors(key.dag_id)
    except AirflowError:
        import_errors = []

    dag_path = Path(dags_dir)
    if dag_source and dag_source.fileloc:
        candidate = dag_path / Path(dag_source.fileloc).name
        if candidate.exists():
            dag_path = candidate

    return Incident(
        task_instance=task_instance,
        log=log,
        dag_source=dag_source,
        history=history,
        deploys=recent_deploys(dag_path, limit=config.ingest.history_runs),
        import_errors=import_errors,
    )


def save_fixture(incident: Incident, path: Path | str) -> Path:
    """Freeze an ingested incident to disk as an eval/integration fixture."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(incident.model_dump_json(indent=2), encoding="utf-8")
    return target


def load_fixture(path: Path | str) -> Incident:
    """Load a frozen incident. No network, no LLM."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return Incident.model_validate(payload)


def incident_key(incident: Incident) -> IncidentKey:
    ti = incident.task_instance
    return IncidentKey(
        dag_id=ti.dag_id,
        task_id=ti.task_id,
        run_id=ti.run_id,
        try_number=ti.try_number or 1,
    )
