from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "prf_ai_pipeline",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    # Real source of truth for workflow status is the workflow_runs table (see
    # tasks.py) — the result backend exists only for Celery-level task
    # introspection/retries, never read by the API.
    result_expires=3600,
)
