from celery import Celery
from celery.signals import worker_ready
from opentelemetry.instrumentation.celery import CeleryInstrumentor

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.telemetry import configure_tracing

configure_logging()
configure_tracing(service_name="prf-celery-worker")
# Propagates trace context through task message headers on publish/consume,
# so a trace started by POST /workflow/run continues into run_workflow
# instead of starting over as a disconnected trace on the worker side.
CeleryInstrumentor().instrument()

# Import registers the worker_process_init/task_prerun/task_postrun signal
# handlers that back GET :celery_metrics_port/metrics -- unused directly, the
# side effect of importing is the point.
from app.workers import metrics as _metrics  # noqa: E402,F401

settings = get_settings()

celery_app = Celery(
    "prf_ai_pipeline",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks", "app.workers.agent_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    # Agent control-plane tasks get their own queue (and worker) -- see docker-compose.yml.
    task_routes={
        "run_campaign_agent": {"queue": "agent"},
        "resume_campaign_agent": {"queue": "agent"},
    },
    # Real source of truth for workflow status is the workflow_runs table (see
    # tasks.py) — the result backend exists only for Celery-level task
    # introspection/retries, never read by the API.
    result_expires=3600,
)


@worker_ready.connect
def _recover_stalled_work_on_startup(sender=None, **_kwargs) -> None:
    """A worker that crashed mid-task leaves runs in `running` that nothing will
    advance; the restarted worker is the natural moment to look.

    Each sweep is sent twice: now, and again once the stall TTL has elapsed. The
    second matters more than it looks — a worker that crashes and restarts
    quickly leaves work whose heartbeat/claim is still *fresh* at startup, so an
    immediate sweep correctly ignores it (it cannot tell dead from slow). Only
    after the TTL can it be called stalled, so the delayed sweep is what catches
    the common case. Enqueued rather than run inline so a slow DB can't delay
    the worker becoming ready."""
    settings = get_settings()
    for name, ttl in (
        ("recover_stale_releases", settings.release_claim_ttl_seconds),
        ("recover_stalled_runs", settings.run_stall_ttl_seconds),
    ):
        celery_app.send_task(name)
        celery_app.send_task(name, countdown=ttl + 15)
