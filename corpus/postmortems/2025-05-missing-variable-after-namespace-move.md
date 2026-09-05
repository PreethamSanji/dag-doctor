---
title: "Postmortem: missing Airflow Variable after namespace move"
source_url: https://github.com/PreethamSanji/dag-doctor/blob/main/corpus/postmortems/2025-05-missing-variable-after-namespace-move.md
license: CC-BY-4.0
tags: [config_error, postmortem, variables]
---

# Summary

On 2025-05-19, every task in `export_customer_extract` failed within two seconds
of starting, immediately after the platform team moved Airflow to a new
Kubernetes namespace. Staging was unaffected.

# What the logs showed

```
Traceback (most recent call last):
  File "/opt/airflow/dags/export_customer_extract.py", line 41, in extract
    bucket = Variable.get("s3_bucket")
  File "/home/airflow/.local/lib/python3.12/site-packages/airflow/models/variable.py", line 144, in get
    raise KeyError(f"Variable {key} does not exist")
KeyError: 'Variable s3_bucket does not exist'
```

# Root cause

`config_error`. The variable was supplied through the Helm chart's `env` block
as `AIRFLOW_VAR_S3_BUCKET`. The namespace migration re-applied the chart from a
values file that predated the variable being added, so the environment variable
was silently absent. The metadata database was new in the target namespace, so
there was no database-backed value to fall back to either.

# Signals that identified it quickly

1. **Failure latency.** Two seconds. A data or external-service problem takes
   longer; a configuration lookup fails at once.
2. **Blast radius.** Every task in the DAG, on every run, including reruns of
   runs that had previously succeeded. Data problems are partition-shaped;
   configuration problems are total.
3. **The raising frame.** `airflow/models/variable.py`, not the DAG file. A
   `KeyError` from a dict in task code would have named the DAG file.

# Fix

Added the missing `AIRFLOW_VAR_S3_BUCKET` entry to the production values file
and re-applied. Added a CI check comparing the variable keys referenced in DAG
source against the keys present in each environment's values file.

# Lesson for triage

Fast, total, and raised from inside `airflow/` means configuration. Do not
diagnose the DAG code when the DAG code is only the messenger.
