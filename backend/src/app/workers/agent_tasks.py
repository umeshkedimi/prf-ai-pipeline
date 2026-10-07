import asyncio
import uuid

from app.campaign_agent.runtime import run_agent
from app.core.logging import get_logger
from app.db.base import reset_engine
from app.db.session import db_session
from app.harness import store
from app.workers.agent_recovery import find_stalled_agent_run_ids, reclaim_stalled_agent_run
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="run_campaign_agent")
def run_campaign_agent(agent_run_id: str) -> None:
    asyncio.run(_run(agent_run_id, resume=None))


@celery_app.task(name="continue_campaign_agent")
def continue_campaign_agent(agent_run_id: str) -> None:
    """Continues a run from its last checkpoint after its worker died."""
    asyncio.run(_run(agent_run_id, resume=None, recovering=True))


@celery_app.task(name="recover_stalled_agent_runs")
def recover_stalled_agent_runs() -> int:
    return asyncio.run(_recover())


async def _recover() -> int:
    await reset_engine()
    recovered = 0
    try:
        async with db_session() as session:
            candidates = await find_stalled_agent_run_ids(session)
            for run_id in candidates:
                if await reclaim_stalled_agent_run(session, run_id):
                    continue_campaign_agent.delay(str(run_id))
                    log.warning("campaign_agent.recovering_stalled_run", agent_run_id=str(run_id))
                    recovered += 1
    finally:
        await reset_engine()
    return recovered


@celery_app.task(name="resume_campaign_agent")
def resume_campaign_agent(agent_run_id: str, decision: dict) -> None:
    asyncio.run(_run(agent_run_id, resume=decision))


async def _run(agent_run_id: str, resume: dict | None, recovering: bool = False) -> None:
    """Same engine-reset discipline as workers/tasks.py: the asyncpg engine is bound to
    an event loop, and each asyncio.run() makes a new one."""
    await reset_engine()
    run_uuid = uuid.UUID(agent_run_id)
    try:
        await run_agent(run_uuid, resume, recovering=recovering)
    except Exception as exc:  # noqa: BLE001 - record the failure on the run, then re-raise for Celery
        log.exception("campaign_agent.failed", agent_run_id=agent_run_id)
        await store.finish_run(run_uuid, "failed", {"error": f"{type(exc).__name__}: {exc}"[:500]})
        raise
    finally:
        await reset_engine()
