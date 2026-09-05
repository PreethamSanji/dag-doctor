"""Ground truth: dependency_error.

The provider package is not installed in the image. The import sits inside the
task callable rather than at module level, so the DAG parses cleanly and only
this one task fails - which is what separates it from a parse-time import error.
"""

from __future__ import annotations

import pendulum
from airflow.decorators import dag, task


@dag(
    dag_id="missing_provider_load",
    schedule=None,
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    tags=["broken", "dependency_error"],
)
def missing_provider_load():
    @task
    def load_to_warehouse() -> None:
        print("Opening warehouse connection")
        from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook

        SnowflakeHook(snowflake_conn_id="warehouse").run("select 1")

    load_to_warehouse()


missing_provider_load()
