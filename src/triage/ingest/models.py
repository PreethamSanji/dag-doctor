"""Typed views over the Airflow REST API responses we consume.

These are deliberately narrow: only the fields triage actually reads. Anything
here is *structural* evidence - it comes from the Airflow API, not from log
text - which is what lets the card assert state a log line cannot override.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskInstance(BaseModel):
    """One task instance as Airflow reports it."""

    # ``populate_by_name`` lets a frozen fixture (which serializes ``run_id``)
    # round-trip through the same model as a live API payload (``dag_run_id``).
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    dag_id: str
    task_id: str
    run_id: str = Field(alias="dag_run_id")
    try_number: int = 1
    state: str | None = None
    operator: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    duration: float | None = None
    max_tries: int | None = None
    pool: str | None = None
    queue: str | None = None
    hostname: str | None = None
    executor_config: str | None = None
    note: str | None = None

    @property
    def failed(self) -> bool:
        return (self.state or "").lower() in {"failed", "up_for_retry", "upstream_failed"}


class TaskRunSummary(BaseModel):
    """A historical run of the same task, for spotting 'when did this start failing'."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    try_number: int
    state: str | None
    start_date: datetime | None = None
    duration: float | None = None


class DagSource(BaseModel):
    """DAG file contents. Untrusted: it is code, and it is sanitized like any log."""

    model_config = ConfigDict(extra="ignore")

    dag_id: str
    fileloc: str
    source: str
    last_parsed_time: datetime | None = None


class DeployEvent(BaseModel):
    """A change to the DAG file, from git history over the DAGs folder."""

    model_config = ConfigDict(extra="ignore")

    sha: str
    author: str
    committed_at: datetime | None = None
    subject: str
    files: list[str] = Field(default_factory=list)


class TaskLog(BaseModel):
    """Raw task log for one try. Untrusted input."""

    model_config = ConfigDict(extra="ignore")

    dag_id: str
    task_id: str
    run_id: str
    try_number: int
    content: str

    def tail(self, lines: int) -> str:
        split = self.content.splitlines()
        return "\n".join(split[-lines:]) if lines > 0 else self.content


class Incident(BaseModel):
    """Everything ingested for one failed task instance."""

    model_config = ConfigDict(extra="ignore")

    task_instance: TaskInstance
    log: TaskLog
    dag_source: DagSource | None = None
    history: list[TaskRunSummary] = Field(default_factory=list)
    deploys: list[DeployEvent] = Field(default_factory=list)
    dag_details: dict[str, Any] = Field(default_factory=dict)
    import_errors: list[str] = Field(default_factory=list)

    @property
    def key(self) -> str:
        ti = self.task_instance
        return f"{ti.dag_id}/{ti.task_id}/{ti.run_id}#{ti.try_number}"
