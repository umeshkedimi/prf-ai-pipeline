"""Prometheus metrics for the Celery worker.

The worker process has no HTTP server of its own (unlike the API, which
exposes GET /metrics via prometheus-fastapi-instrumentator in main.py), so
this starts a dedicated one via Celery's worker_process_init signal and
records task-level metrics via task_prerun/task_postrun/task_failure.
Pipeline-level counters (runs by terminal status, review pause rate) are
recorded separately from workers/tasks.py, since that's where the terminal
status is actually decided.
"""

import time

from celery import signals
from prometheus_client import Counter, Histogram, start_http_server

from app.core.config import get_settings

celery_task_duration_seconds = Histogram(
    "celery_task_duration_seconds", "Celery task execution time", ["task_name"]
)
celery_task_total = Counter(
    "celery_task_total", "Celery tasks completed", ["task_name", "outcome"]
)
pipeline_runs_total = Counter(
    "pipeline_runs_total", "Workflow runs reaching a terminal state", ["status"]
)
pipeline_human_review_pauses_total = Counter(
    "pipeline_human_review_pauses_total", "Workflow runs pausing for human review", ["stage"]
)

_task_started_at: dict[str, float] = {}


@signals.worker_process_init.connect
def _start_metrics_server(**_kwargs) -> None:
    start_http_server(get_settings().celery_metrics_port)


@signals.task_prerun.connect
def _record_task_start(task_id: str, **_kwargs) -> None:
    _task_started_at[task_id] = time.monotonic()


@signals.task_postrun.connect
def _record_task_end(task_id: str, task, state: str, **_kwargs) -> None:
    # Fires for every outcome (success, failure, retry) with `state` already
    # reflecting which one — no separate task_failure handler needed, and
    # adding one would double-count failures against this same counter.
    started = _task_started_at.pop(task_id, None)
    if started is not None:
        celery_task_duration_seconds.labels(task_name=task.name).observe(time.monotonic() - started)
    celery_task_total.labels(task_name=task.name, outcome=state.lower()).inc()
