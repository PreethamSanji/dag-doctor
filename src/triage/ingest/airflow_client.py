"""Airflow REST client.

Talks to the Airflow 2.x stable REST API (``/api/v1``) with basic auth, which is
what ``docker compose up -d`` gives us locally. Every method returns typed
models; none of them sanitize - sanitization happens at the boundary where
content enters model context, so tests can assert on raw ingestion.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from triage.ingest.models import (
    DagSource,
    TaskInstance,
    TaskLog,
    TaskRunSummary,
)

#: Airflow's log endpoint returns the log wrapped in a Python-repr-ish envelope
#: when ``full_content`` is requested as text. Strip it to get the real body.
_LOG_ENVELOPE = re.compile(r"\A\s*\[\('[^']*',\s*[\"'](.*)[\"']\)\]\s*\Z", re.DOTALL)


class AirflowError(RuntimeError):
    """The Airflow API rejected a request or returned something unusable."""


class AirflowClient:
    """Thin, typed wrapper over the endpoints triage needs."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(
            base_url=f"{self.base_url}/api/v1",
            auth=(username, password),
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AirflowClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, path: str, **params: Any) -> httpx.Response:
        response = self._client.get(path, params={k: v for k, v in params.items() if v is not None})
        if response.status_code >= 400:
            raise AirflowError(f"GET {path} -> {response.status_code}: {response.text[:300]}")
        return response

    def get_task_instance(self, dag_id: str, run_id: str, task_id: str) -> TaskInstance:
        payload = self._get(f"/dags/{dag_id}/dagRuns/{run_id}/taskInstances/{task_id}").json()
        return TaskInstance.model_validate(payload)

    def get_log(self, dag_id: str, run_id: str, task_id: str, try_number: int) -> TaskLog:
        response = self._client.get(
            f"/dags/{dag_id}/dagRuns/{run_id}/taskInstances/{task_id}/logs/{try_number}",
            params={"full_content": "true"},
            headers={"Accept": "text/plain"},
        )
        if response.status_code >= 400:
            raise AirflowError(f"log fetch -> {response.status_code}: {response.text[:300]}")
        content = response.text
        if match := _LOG_ENVELOPE.match(content):
            content = match.group(1).encode().decode("unicode_escape")
        return TaskLog(
            dag_id=dag_id,
            task_id=task_id,
            run_id=run_id,
            try_number=try_number,
            content=content,
        )

    def get_dag_details(self, dag_id: str) -> dict[str, Any]:
        return self._get(f"/dags/{dag_id}/details").json()

    def get_dag_source(self, dag_id: str) -> DagSource:
        """Fetch DAG source via the file token in the DAG details payload."""
        details = self.get_dag_details(dag_id)
        file_token = details.get("file_token")
        if not file_token:
            raise AirflowError(f"no file_token for dag {dag_id}")
        response = self._client.get(f"/dagSources/{file_token}", headers={"Accept": "text/plain"})
        if response.status_code >= 400:
            raise AirflowError(f"dag source -> {response.status_code}: {response.text[:300]}")
        return DagSource(
            dag_id=dag_id,
            fileloc=details.get("fileloc", ""),
            source=response.text,
            last_parsed_time=details.get("last_parsed_time"),
        )

    def get_task_history(self, dag_id: str, task_id: str, limit: int = 10) -> list[TaskRunSummary]:
        """Recent instances of the same task across runs, newest first."""
        payload = self._get(
            f"/dags/{dag_id}/dagRuns/~/taskInstances",
            limit=limit,
            order_by="-start_date",
        ).json()
        history: list[TaskRunSummary] = []
        for item in payload.get("task_instances", []):
            if item.get("task_id") != task_id:
                continue
            history.append(
                TaskRunSummary(
                    run_id=item.get("dag_run_id", ""),
                    try_number=item.get("try_number", 1),
                    state=item.get("state"),
                    start_date=item.get("start_date"),
                    duration=item.get("duration"),
                )
            )
        return history[:limit]

    def get_import_errors(self, dag_id: str | None = None) -> list[str]:
        """DAG-parse errors, which are how config and import failures usually surface."""
        payload = self._get("/importErrors", limit=100).json()
        errors: list[str] = []
        for item in payload.get("import_errors", []):
            filename = item.get("filename", "")
            if dag_id and dag_id not in filename:
                continue
            errors.append(f"{filename}: {item.get('stack_trace', '')}")
        return errors
