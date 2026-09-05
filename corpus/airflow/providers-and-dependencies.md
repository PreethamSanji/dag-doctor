---
title: Airflow Providers, Imports, and Dependency Failures
source_url: https://airflow.apache.org/docs/apache-airflow-providers/index.html
license: Apache-2.0
tags: [dependency_error, providers, imports]
---

# Import failures

`ModuleNotFoundError: No module named 'airflow.providers.snowflake'` means the
provider package is not installed in the image the worker runs. Providers are
distributed separately from core Airflow: `apache-airflow-providers-snowflake`,
`apache-airflow-providers-amazon`, and so on. Installing the client library
alone (`snowflake-connector-python`) does not install the provider.

Where the error appears tells you what broke:

- **At DAG parse time** - the import is at module level, so the whole file fails
  to parse. It appears in `/api/v1/importErrors` and in the scheduler log, and
  *every* task in that file is affected, not just one.
- **Inside a task** - the import is inside the callable, so only that task fails
  and the rest of the DAG runs. This is common with `PythonVirtualenvOperator`
  and with lazily imported clients.

# Version conflicts

`ImportError: cannot import name 'X' from 'Y'` and
`AttributeError: module 'Y' has no attribute 'X'` usually mean an installed
package is a different major version than the code expects. Airflow constrains
its own dependency set through constraint files pinned to the Airflow version;
installing a package with `pip install` inside a running container without those
constraints frequently produces exactly this failure on the next worker restart -
and only on the workers that restarted, which is why it can look intermittent.

# Distinguishing dependency from platform errors

A `ModuleNotFoundError` naming a third-party package is `dependency_error`. An
`ImportError` from inside `airflow/` core itself, or a worker that cannot start
at all, is `platform_error`. If the DAG parsed and ran successfully yesterday
with no code change, correlate against image or requirements changes before
concluding the code is at fault.
