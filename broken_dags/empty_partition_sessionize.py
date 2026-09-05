"""Ground truth: upstream_data.

The exception is raised inside DAG code (`IndexError`), but the code is correct
for non-empty input and the log line before the traceback says `0 files matched`.
This is the case that punishes triage for reading only the last line.
"""

from __future__ import annotations

import pendulum
from airflow.decorators import dag, task

#: Stands in for the producing job's output. Empty today: the producer is paused.
PARTITION_FILES: list[str] = []


@dag(
    dag_id="empty_partition_sessionize",
    schedule=None,
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    tags=["broken", "upstream_data"],
)
def empty_partition_sessionize():
    @task
    def discover(**context) -> list[str]:
        prefix = f"s3://events-prod/dt={context['ds']}/"
        print(f"Reading {prefix}")
        print(f"{len(PARTITION_FILES)} files matched")
        return PARTITION_FILES

    @task
    def compute_sessions(files: list[str]) -> int:
        frames = [{"event_ts": index} for index in range(len(files))]
        first_ts = frames[0]["event_ts"]
        print(f"First event at {first_ts}")
        return len(frames)

    compute_sessions(discover())


empty_partition_sessionize()
