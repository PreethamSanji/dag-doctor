"""Ground truth: platform_error.

The task code is correct and does nothing but wait. It dies because the worker
holding it is evicted and the scheduler reaps it: `Recorded pid does not match`,
then SIGTERM, then `Negsignal.SIGTERM`. No traceback from DAG code, no memory
growth, and the same task succeeded yesterday with the same input - the evidence
that separates a platform kill from a code error or an OOM.

Reproduce by restarting the worker (or letting the node pool preempt it) while
this task holds its slot.
"""

from __future__ import annotations

import time

import pendulum
from airflow.decorators import dag, task

HOLD_SECONDS = 900


@dag(
    dag_id="zombie_heartbeat_wait",
    schedule=None,
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    tags=["broken", "platform_error"],
)
def zombie_heartbeat_wait():
    @task
    def wait_for_slot() -> int:
        print(f"Holding a worker slot for {HOLD_SECONDS}s")
        time.sleep(HOLD_SECONDS)
        return HOLD_SECONDS

    wait_for_slot()


zombie_heartbeat_wait()
