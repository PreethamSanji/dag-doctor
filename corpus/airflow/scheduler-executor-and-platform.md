---
title: Scheduler, Executor, and Platform Failures
source_url: https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/scheduler.html
license: Apache-2.0
tags: [platform_error, scheduler, executor]
---

# Zombie tasks

`Detected zombie job` in the scheduler log means a task instance was marked
running but stopped sending heartbeats for longer than
`scheduler.scheduler_zombie_task_threshold`. The task log usually ends without a
traceback. Two very different causes share this signature:

- The worker process died (OOM kill, node eviction, spot reclaim) -
  `resource_exhaustion` or `platform_error` depending on which.
- The worker is alive but the database connection stalled - `platform_error`.

The distinguishing evidence is whether other tasks on the same host failed at the
same moment. One task, one host: look at that task's memory. Many tasks, one
host: look at the host.

# Upstream failed

`state: upstream_failed` is never the root cause. The task never ran; a
dependency failed. Triage the upstream task instead, and say so explicitly
rather than diagnosing the downstream task's code.

# DAG parse errors

Import errors from the DAG processor appear in `/api/v1/importErrors` and block
*all* DAGs in the offending file. Because the file never parses, tasks may not
appear in the UI at all, and a run scheduled before the break will show tasks
stuck in `scheduled`. Airflow keeps serving the last successfully parsed version
of a DAG until `dag_dir_list_interval` picks up the change, so a broken deploy
can look intermittent for the first few minutes.

# Executor-specific notes

- `LocalExecutor` - task failures surface directly in the task log; scheduler
  restarts kill running tasks.
- `CeleryExecutor` - `Task ... raised unexpected: AirflowException('Celery
  command failed')` points at the broker or worker, not the DAG.
- `KubernetesExecutor` - a pod that never reached `Running` gives an empty task
  log; the real error is in the pod events (`ImagePullBackOff`,
  `CreateContainerConfigError`, `OOMKilled`), which is `platform_error`,
  `config_error`, and `resource_exhaustion` respectively.
