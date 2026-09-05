"""Ground truth: config_error.

`AIRFLOW_VAR_S3_BUCKET` is never set, so `Variable.get` raises from inside
`airflow/models/variable.py` about two seconds into the task. Fast, total, and
raised from Airflow's own code - the config-error signature.
"""

from __future__ import annotations

import pendulum
from airflow.decorators import dag, task
from airflow.models import Variable


@dag(
    dag_id="missing_variable_extract",
    schedule=None,
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    tags=["broken", "config_error"],
)
def missing_variable_extract():
    @task
    def extract() -> str:
        print("Resolving destination bucket from Airflow Variables")
        bucket = Variable.get("s3_bucket")
        print(f"Writing extract to s3://{bucket}/customers/")
        return bucket

    @task
    def confirm(bucket: str) -> None:
        print(f"Extract complete for {bucket}")

    confirm(extract())


missing_variable_extract()
