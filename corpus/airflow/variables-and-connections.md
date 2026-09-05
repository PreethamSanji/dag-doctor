---
title: Airflow Variables and Connections
source_url: https://airflow.apache.org/docs/apache-airflow/stable/howto/variable.html
license: Apache-2.0
tags: [config_error, variables, connections]
---

# Variables

`Variable.get("key")` raises `KeyError: 'Variable key does not exist'` when the
key is not defined in the metadata database and no environment fallback exists.
The traceback surfaces from `airflow/models/variable.py` and the task fails
immediately, usually within a second of starting - a fast failure with no
partial work is the signature of a missing variable rather than a data problem.

Variables can be supplied three ways, checked in this order:

1. Environment variable `AIRFLOW_VAR_{KEY_UPPERCASED}`. `AIRFLOW_VAR_S3_BUCKET`
   backs `Variable.get("s3_bucket")`. This is the mechanism Helm deployments use.
2. A secrets backend configured under `[secrets] backend`.
3. The Airflow metadata database, populated by the UI, CLI, or API.

Use `Variable.get("key", default_var=None)` when absence is legitimate. Calling
`Variable.get` at DAG parse time (module top level) rather than inside a task
means a missing variable breaks *parsing* for every DAG in the file and shows up
as an import error rather than a task failure.

# Connections

`BaseHook.get_connection(conn_id)` raises
`AirflowNotFoundException: The conn_id 'x' isn't defined` when the connection is
absent. Connections resolve from `AIRFLOW_CONN_{CONN_ID_UPPERCASED}` as a URI, a
secrets backend, or the metadata database.

A connection that exists but has the wrong host, port, or credentials produces a
different signature: the task runs longer, then fails inside the provider's
client library with a connection refused, DNS, or authentication error. That is
an `external_service` or `config_error` boundary case - the distinguishing
evidence is whether the connection resolved at all.

# Telling config errors from code errors

A `KeyError` from `Variable.get` and a `KeyError` from a dictionary in task code
look similar in a one-line log grep. Read the frame: if the raising frame is in
`airflow/models/variable.py` or `airflow/hooks/base.py`, it is configuration. If
it is in the DAG file, it is code.
