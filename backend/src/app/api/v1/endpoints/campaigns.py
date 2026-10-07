import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_auth import get_current_user, require_role
from app.campaigns.membership import status_counts
from app.db.models import Campaign
from app.schemas.campaigns import CampaignCreate, CampaignRead, CampaignSummary

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post(
    "/campaigns",
    response_model=CampaignRead,
    status_code=201,
    dependencies=[Depends(require_role("admin"))],
)
async def create_campaign(payload: CampaignCreate, session: AsyncSession = Depends(get_db)) -> Campaign:
    campaign = Campaign(**payload.model_dump())
    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)
    return campaign


@router.get("/campaigns", response_model=list[CampaignRead])
async def list_campaigns(session: AsyncSession = Depends(get_db)) -> list[Campaign]:
    result = await session.execute(select(Campaign).order_by(Campaign.created_at.desc()).limit(100))
    return list(result.scalars().all())


@router.get("/campaigns/{campaign_id}", response_model=CampaignSummary)
async def get_campaign(campaign_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> CampaignSummary:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    counts = await status_counts(session, campaign_id)
    return CampaignSummary(
        **CampaignRead.model_validate(campaign).model_dump(),
        donor_counts=counts,
        total_donors=sum(counts.values()),
    )
