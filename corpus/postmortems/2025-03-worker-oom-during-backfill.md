---
title: "Postmortem: worker OOM during month-end backfill"
source_url: https://github.com/PreethamSanji/dag-doctor/blob/main/corpus/postmortems/2025-03-worker-oom-during-backfill.md
license: CC-BY-4.0
tags: [resource_exhaustion, postmortem, oom]
---

# Summary

On 2025-03-04 the `revenue_rollup.aggregate_daily` task failed on 6 of 31
backfilled runs. Failures were not reproducible when re-run individually. Total
time to diagnosis: 90 minutes, most of it spent looking for a code bug that did
not exist.

# What the logs showed

```
[2025-03-04 02:14:41] INFO - Loaded 4,118,442 rows
[2025-03-04 02:15:02] INFO - Joining dimension tables
[2025-03-04 02:15:19] ERROR - Task exited with return code Negsignal.SIGKILL
```

No traceback. No exception. The log simply stops. That is the fingerprint of an
external kill, not an application error - Python never got to run a handler.

# Root cause

`resource_exhaustion`. The task loaded the full month into a pandas DataFrame
and then called `concat` on a list of per-day frames, roughly doubling peak
memory. Worker memory limit was `2Gi` (`workers.resources.limits.memory` in the
Helm values). Backfill ran 16 tasks concurrently on 2 workers, so peak usage per
pod was a multiple of the single-task profile - which is why single re-runs
always passed and made it look intermittent.

# Why it was mis-triaged initially

The first responder searched the log for "Error" and found only the SIGKILL
line, then assumed a code bug because the task had changed the week before. The
deploy correlation was a coincidence: the change was a column rename.

The signal that would have shortened this: concurrency. Failures clustered by
*time*, not by *data partition*. Six failures all fell in the two windows where
the scheduler had the most parallel tasks in flight.

# Fix

Chunked the read with `chunksize=250_000`, and raised
`workers.resources.limits.memory` to `4Gi` as a safety margin. Added
`max_active_tasks` on the DAG to cap backfill concurrency at 4.

# Lesson for triage

Return code -9 with no traceback is `resource_exhaustion` until proven
otherwise. Check concurrency before checking the diff.
