---
title: "Postmortem: empty upstream partition mistaken for a code bug"
source_url: https://github.com/PreethamSanji/dag-doctor/blob/main/corpus/postmortems/2025-07-empty-upstream-partition.md
license: CC-BY-4.0
tags: [upstream_data, postmortem]
---

# Summary

On 2025-07-08 `sessionize_events.compute_sessions` failed with an `IndexError`
raised from the DAG's own code. The change that "caused" it had shipped eleven
days earlier and had run successfully every day since.

# What the logs showed

```
[2025-07-08 06:02:11] INFO - Reading s3://events-prod/dt=2025-07-07/
[2025-07-08 06:02:12] INFO - 0 files matched
Traceback (most recent call last):
  File "/opt/airflow/dags/sessionize_events.py", line 88, in compute_sessions
    first_ts = frames[0]["event_ts"].min()
IndexError: list index out of range
```

# Root cause

`upstream_data`. The producing job on the events platform had been paused for a
capacity migration, so the `dt=2025-07-07` prefix was empty. The task code
assumed at least one file. The exception was raised in our code, but our code was
not what changed.

# The discriminating question

*Would the same code have succeeded on yesterday's input?* Yes - it had, for
eleven days. That single question separates `upstream_data` from `code_error`
faster than reading the diff, and it is answerable from the task's own run
history without leaving Airflow.

# Signals

- The log line before the traceback (`0 files matched`) is the real finding. The
  exception is a downstream symptom.
- Task history showed 11 consecutive successes and one failure, with no deploy
  in the window.
- Other consumers of the same prefix failed in the same hour with different
  exceptions - a fan-out pattern that points upstream, not at any one DAG.

# Fix

Added an explicit guard that fails with a descriptive `AirflowSkipException`
when the partition is empty, plus an `ExternalTaskSensor` on the producing DAG
so the dependency is expressed rather than assumed.

# Lesson for triage

An exception raised inside DAG code is not sufficient evidence for
`code_error`. Check run history and the lines immediately before the traceback.
