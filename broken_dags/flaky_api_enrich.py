"""Ground truth: external_service.

The task's code and connection are correct; the remote endpoint is unreachable.
The exception names a remote host and arrives after a connection timeout, not
immediately - the latency itself is evidence against a config error.
"""

from __future__ import annotations

import pendulum
from airflow.decorators import dag, task

ENDPOINT = "http://enrichment.invalid:8443/v1/customers"


@dag(
    dag_id="flaky_api_enrich",
    schedule=None,
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    tags=["broken", "external_service"],
)
def flaky_api_enrich():
    @task
    def enrich() -> dict:
        import httpx

        print(f"POST {ENDPOINT}")
        response = httpx.post(ENDPOINT, json={"ids": [1, 2, 3]}, timeout=5.0)
        response.raise_for_status()
        return response.json()

    enrich()


flaky_api_enrich()
