---
title: Retries, Timeouts, Pools, and Resource Exhaustion
source_url: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/tasks.html
license: Apache-2.0
tags: [resource_exhaustion, timeouts, pools]
---

# The signatures worth memorising

| Log signature | What it means | Category |
| --- | --- | --- |
| `Task exited with return code Negsignal.SIGKILL` or `return code -9` | The kernel OOM killer stopped the process | resource_exhaustion |
| `Received SIGTERM. Terminating subprocesses` followed by a clean exit | Airflow asked the task to stop - timeout, clear, or scheduler eviction | resource_exhaustion or platform_error |
| `AirflowTaskTimeout: Timeout, PID: ...` | `execution_timeout` elapsed | resource_exhaustion if contention, code_error if a hung call |
| `OSError: [Errno 28] No space left on device` | Disk full, often logs or a spill file | resource_exhaustion |
| `Task is in the 'running' state which is not a valid state for execution. The task must be cleared` | The scheduler and the worker disagree; usually a lost heartbeat | platform_error |

# Return code -9 is not a code bug

A SIGKILL leaves no Python traceback, because the process never got to run an
exception handler. The absence of a traceback in a task that produced normal
progress logs and then stopped mid-stream is itself the evidence. Look for a
memory-shaped workload just before the cut: a `read_csv` without chunking, a
`pandas.concat` over a growing list, a `.collect()`.

# Pools and slots

A task stuck in `scheduled` or `queued` with no worker log at all is not failing
in the task sense - it never started. Check the pool's slot count and the number
of running tasks in it. `Pool` starvation shows as long queue times followed by
either eventual execution or an SLA miss, never as a traceback.

# execution_timeout vs. dagrun_timeout

`execution_timeout` is per task and raises `AirflowTaskTimeout` inside the task
process. `dagrun_timeout` is per DAG run and marks still-running tasks as failed
from the scheduler side, which produces a task log ending abruptly with a
SIGTERM and no exception. Confusing the two leads to fixing the wrong knob.
