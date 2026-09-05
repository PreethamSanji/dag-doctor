"""Ground truth: resource_exhaustion.

Allocates until the container's memory limit kills it. The task log ends
mid-stream with no traceback - the process never gets to raise - which is the
distinguishing evidence against a code error.

Set `workers.resources.limits.memory` (or the compose container's memory) low
enough that this is killed rather than swapping the host.
"""

from __future__ import annotations

import pendulum
from airflow.decorators import dag, task

CHUNK_MB = 64
MAX_CHUNKS = 512


@dag(
    dag_id="memory_hog_rollup",
    schedule=None,
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    tags=["broken", "resource_exhaustion"],
)
def memory_hog_rollup():
    @task
    def aggregate() -> int:
        print("Loading month-to-date revenue rows")
        held: list[bytes] = []
        for chunk in range(MAX_CHUNKS):
            held.append(b"\0" * (CHUNK_MB * 1024 * 1024))
            print(f"Held {(chunk + 1) * CHUNK_MB} MB; joining dimension tables")
        return len(held)

    aggregate()


memory_hog_rollup()
