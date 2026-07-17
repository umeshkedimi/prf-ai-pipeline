import asyncio
import uuid
from datetime import UTC, datetime

from app.core.config import get_settings
from app.db.base import reset_engine
from app.db.models import WorkflowRun
from app.db.session import db_session
from app.graph.builder import build_graph
from app.workers.celery_app import celery_app


@celery_app.task(name="run_donor_verification_workflow")
def run_donor_verification_workflow(workflow_run_id: str) -> None:
    """Sync Celery entrypoint (default prefork pool) bridging into the async
    graph. Each call gets a fresh event loop via asyncio.run(), so the cached
    DB engine must be reset around it — see db/base.py:reset_engine()."""
    asyncio.run(_run(workflow_run_id))


async def _run(workflow_run_id: str) -> None:
    await reset_engine()
    try:
        run_uuid = uuid.UUID(workflow_run_id)

        async with db_session() as session:
            run = await session.get(WorkflowRun, run_uuid)
            if run is None:
                return
            run.status = "running"
            run.current_agent = "donor_verification"
            run.started_at = datetime.now(UTC)
            await session.commit()
            donor_id = str(run.donor_id)
            campaign_id = str(run.campaign_id) if run.campaign_id else None

        try:
            async with build_graph() as graph:
                result = await graph.ainvoke(
                    {
                        "workflow_run_id": workflow_run_id,
                        "donor_id": donor_id,
                        "campaign_id": campaign_id,
                    },
                    config={"configurable": {"thread_id": workflow_run_id}},
                )

            verdict = result["verification_result"]
            confidence = verdict["confidence"]
            threshold = get_settings().confidence_threshold_donor_verification
            status = "completed" if confidence >= threshold else "needs_review"

            async with db_session() as session:
                run = await session.get(WorkflowRun, run_uuid)
                run.status = status
                run.current_agent = "donor_verification"
                run.result = verdict
                run.confidence = confidence
                run.completed_at = datetime.now(UTC)
                await session.commit()

        except Exception as exc:
            async with db_session() as session:
                run = await session.get(WorkflowRun, run_uuid)
                run.status = "failed"
                run.error = str(exc)
                run.completed_at = datetime.now(UTC)
                await session.commit()
            raise
    finally:
        await reset_engine()
