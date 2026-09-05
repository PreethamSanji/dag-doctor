"""Ground truth: code_error.

The task builds its own input, so the data is never in question: the code
references a column that the code itself never created. The raising frame is in
the DAG file, and no input, config, or dependency changed.
"""

from __future__ import annotations

import pendulum
from airflow.decorators import dag, task


@dag(
    dag_id="undefined_column_transform",
    schedule=None,
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    tags=["broken", "code_error"],
)
def undefined_column_transform():
    @task
    def build_rows() -> list[dict]:
        return [
            {"customer_id": 1, "amount_cents": 1250, "currency": "usd"},
            {"customer_id": 2, "amount_cents": 990, "currency": "eur"},
        ]

    @task
    def transform(rows: list[dict]) -> list[dict]:
        print(f"Transforming {len(rows)} rows")
        # The producer emits `amount_cents`; this reads `amount_usd`.
        return [{"customer_id": row["customer_id"], "usd": row["amount_usd"] / 100} for row in rows]

    transform(build_rows())


undefined_column_transform()
