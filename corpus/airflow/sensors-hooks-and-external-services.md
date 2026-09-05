---
title: Sensors, Hooks, and External Service Failures
source_url: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/sensors.html
license: Apache-2.0
tags: [external_service, upstream_data, sensors]
---

# When the other system is at fault

`external_service` means a system the task called returned an error, refused the
connection, or timed out - and the task's own code and configuration were
correct. The evidence is a client-library exception naming a remote endpoint:

- `requests.exceptions.ConnectionError`, `ReadTimeout`, or a 5xx `HTTPError`
- `botocore.exceptions.ClientError` with a service-side code such as
  `ThrottlingException` or `ServiceUnavailable`
- `psycopg.OperationalError: connection to server ... failed`
- `google.api_core.exceptions.ServiceUnavailable: 503`

A 401, 403, or `NoCredentialsError` is *not* an external service failure. The
remote system worked correctly and rejected us: that is `config_error`.

# Sensors and upstream data

A sensor that times out (`AirflowSensorTimeout`) is reporting that expected data
never arrived. The root cause is `upstream_data` when the producing job is late
or produced nothing, and `config_error` when the sensor is watching the wrong
path, bucket, or partition.

Distinguish them by whether *anything* landed: an empty prefix at the expected
path points upstream; a populated neighbouring path with a different name points
at the sensor's configuration.

# Empty and malformed input

`upstream_data` also covers input that arrived but was wrong: a zero-row
partition, a schema change that renamed a column, a null in a non-nullable
field. These produce `KeyError`, `IndexError`, or a validation exception *inside*
task code, which is why they are so often mislabelled `code_error`. The test:
would the same code have succeeded on yesterday's input? If yes, the data
changed, not the code.
