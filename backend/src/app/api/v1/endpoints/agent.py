import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_auth import get_current_user, require_role
from app.campaign_agent.prompts import DEFAULT_GOAL
from app.db.models import AgentRun, Campaign, User
from app.harness import store
from app.harness.budget import Budget
from app.schemas.agent import (
    AgentApprovalDecision,
    AgentRunCreate,
    AgentRunDetail,
    AgentRunRead,
    AgentStepRead,
)
from app.workers.agent_tasks import resume_campaign_agent, run_campaign_agent

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post(
    "/campaigns/{campaign_id}/agent/run",
    response_model=AgentRunRead,
    status_code=202,
    dependencies=[Depends(require_role("admin"))],
)
async def start_agent_run(
    campaign_id: uuid.UUID,
    payload: AgentRunCreate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AgentRun:
    """Enqueues the campaign agent and returns immediately; the API never runs the loop."""
    if await session.get(Campaign, campaign_id) is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    budget = Budget(max_steps=payload.max_steps, max_tokens=payload.max_tokens, max_runs=payload.max_runs)
    run_id = await store.create_agent_run(campaign_id, payload.goal or DEFAULT_GOAL, budget, user.id)
    run_campaign_agent.delay(str(run_id))
    return await session.get(AgentRun, run_id)


@router.get("/campaigns/{campaign_id}/agent-runs", response_model=list[AgentRunRead])
async def list_agent_runs(campaign_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> list[AgentRun]:
    result = await session.execute(
        select(AgentRun).where(AgentRun.campaign_id == campaign_id).order_by(AgentRun.created_at.desc()).limit(20)
    )
    return list(result.scalars().all())


@router.get("/agent-runs/{agent_run_id}", response_model=AgentRunDetail)
async def get_agent_run(agent_run_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> AgentRunDetail:
    run = await session.get(AgentRun, agent_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="agent run not found")
    steps = [AgentStepRead(**s) for s in await store.load_steps(agent_run_id)]
    return AgentRunDetail(**AgentRunRead.model_validate(run).model_dump(), steps=steps)


@router.post(
    "/agent-runs/{agent_run_id}/approval",
    response_model=AgentRunRead,
    status_code=202,
    dependencies=[Depends(require_role("admin"))],
)
async def decide_approval(
    agent_run_id: uuid.UUID,
    payload: AgentApprovalDecision,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AgentRun:
    """Answers the irreversible call the agent is paused on. `tool` must match the
    pending call (409 otherwise), the claim is one atomic UPDATE (409 for the loser of
    a race), and the reviewer is the authenticated user, never a client-supplied name."""
    run = await session.get(AgentRun, agent_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="agent run not found")
    pending = await store.claim_approval(agent_run_id)
    if pending is None:
        raise HTTPException(status_code=409, detail="no approval is pending for this run")
    if pending.get("tool") != payload.tool:
        await store.request_approval(agent_run_id, pending)  # hand the claim back
        raise HTTPException(status_code=409, detail=f"pending approval is for '{pending.get('tool')}'")
    try:
        resume_campaign_agent.delay(
            str(agent_run_id), {"approved": payload.approve, "reviewer": user.email, "notes": payload.notes}
        )
    except Exception as exc:  # noqa: BLE001 - broker down: give the approval back so it can be retried
        await store.request_approval(agent_run_id, pending)
        raise HTTPException(status_code=503, detail="could not enqueue the resume; approval is still pending") from exc
    await session.refresh(run)
    return run
