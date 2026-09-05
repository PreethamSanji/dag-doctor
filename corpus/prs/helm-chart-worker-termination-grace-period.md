---
title: "PR thread: raise worker terminationGracePeriodSeconds default"
source_url: https://github.com/apache/airflow/tree/main/chart
license: Apache-2.0
tags: [platform_error, resource_exhaustion, helm, review]
---

# Context

Thread from the Airflow Helm chart discussing why a low
`workers.terminationGracePeriodSeconds` produces task failures that look random
but are perfectly correlated with deploys.

# The reported symptom

> Tasks fail roughly once a week with no traceback. The log ends with
> `Received SIGTERM. Terminating subprocesses.` and then nothing. Re-running the
> task always succeeds.

# The review discussion

**Reviewer A:** That SIGTERM is Kubernetes draining the pod during a rolling
update. The default grace period gives the worker 30 seconds to finish
in-flight tasks; anything longer than 30 seconds gets killed mid-execution. This
is not a task failure - it is a deployment behaviour.

**Reviewer B:** Worth being precise about the log signature, because it is
easily confused with the OOM case. Two distinct endings:

- `Received SIGTERM` then a clean shutdown message - the pod was drained.
- `Task exited with return code Negsignal.SIGKILL` with no SIGTERM before it -
  the OOM killer. The kernel does not send SIGTERM first.

If you see SIGTERM, correlate with deploy times. If you see a bare SIGKILL,
correlate with memory.

**Reviewer A:** Agreed. Also worth noting that `celery.worker_concurrency` above
what the memory limit supports turns every deploy into an OOM event, so the two
can co-occur and the SIGTERM masks the real cause.

# Outcome

Default raised to 600 seconds, with a documentation note that the value must
exceed the p99 task duration, and that tasks longer than the grace period should
be made restartable rather than given a longer window.

# Triage relevance

A task log ending in SIGTERM with no exception is `platform_error` when it
correlates with a deploy or node event, and `resource_exhaustion` when it
correlates with an execution timeout. The correlation, not the log line, is the
evidence.
