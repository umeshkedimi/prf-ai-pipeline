import uuid

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign, Donation, Donor, SuppressionListEntry


class DonorProfile(BaseModel):
    donor_id: str
    external_id: str | None
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str
    do_not_contact: bool
    is_suppressed: bool
    suppression_reason: str | None
    notes: str | None


class DonationRecord(BaseModel):
    donation_id: str
    campaign_id: str | None
    campaign_name: str | None
    amount: float
    donation_date: str
    payment_method: str | None


class DuplicateCandidate(BaseModel):
    donor_id: str
    external_id: str | None
    first_name: str
    last_name: str
    address_line1: str | None
    name_similarity: float
    address_similarity: float


def _parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def get_donor_profile(session: AsyncSession, donor_id: str) -> DonorProfile | None:
    donor_uuid = _parse_uuid(donor_id)
    if donor_uuid is None:
        return None

    donor = await session.get(Donor, donor_uuid)
    if donor is None:
        return None

    suppression = (
        (
            await session.execute(
                select(SuppressionListEntry).where(
                    or_(
                        SuppressionListEntry.donor_id == donor_uuid,
                        SuppressionListEntry.email == donor.email,
                    )
                )
            )
        )
        .scalars()
        .first()
    )

    return DonorProfile(
        donor_id=str(donor.id),
        external_id=donor.external_id,
        first_name=donor.first_name,
        last_name=donor.last_name,
        email=donor.email,
        phone=donor.phone,
        address_line1=donor.address_line1,
        address_line2=donor.address_line2,
        city=donor.city,
        state=donor.state,
        postal_code=donor.postal_code,
        country=donor.country,
        do_not_contact=donor.do_not_contact,
        is_suppressed=suppression is not None,
        suppression_reason=suppression.reason if suppression else None,
        notes=donor.notes,
    )


async def get_donation_history(session: AsyncSession, donor_id: str) -> list[DonationRecord]:
    donor_uuid = _parse_uuid(donor_id)
    if donor_uuid is None:
        return []

    rows = (
        await session.execute(
            select(Donation, Campaign.name)
            .join(Campaign, Campaign.id == Donation.campaign_id, isouter=True)
            .where(Donation.donor_id == donor_uuid)
            .order_by(Donation.donation_date.desc())
        )
    ).all()

    return [
        DonationRecord(
            donation_id=str(donation.id),
            campaign_id=str(donation.campaign_id) if donation.campaign_id else None,
            campaign_name=campaign_name,
            amount=float(donation.amount),
            donation_date=donation.donation_date.isoformat(),
            payment_method=donation.payment_method,
        )
        for donation, campaign_name in rows
    ]


async def find_potential_duplicate_donors(
    session: AsyncSession, name: str, address: str, exclude_donor_id: str
) -> list[DuplicateCandidate]:
    exclude_uuid = _parse_uuid(exclude_donor_id)

    name_sim = func.similarity(func.lower(Donor.first_name + " " + Donor.last_name), func.lower(name))
    addr_sim = func.similarity(func.lower(func.coalesce(Donor.address_line1, "")), func.lower(address))

    stmt = (
        select(Donor, name_sim.label("name_sim"), addr_sim.label("addr_sim"))
        .where(or_(name_sim > 0.3, addr_sim > 0.3))
        .order_by((name_sim + addr_sim).desc())
        .limit(5)
    )
    if exclude_uuid is not None:
        stmt = stmt.where(Donor.id != exclude_uuid)

    rows = (await session.execute(stmt)).all()
    return [
        DuplicateCandidate(
            donor_id=str(donor.id),
            external_id=donor.external_id,
            first_name=donor.first_name,
            last_name=donor.last_name,
            address_line1=donor.address_line1,
            name_similarity=round(float(name_sim_val), 3),
            address_similarity=round(float(addr_sim_val), 3),
        )
        for donor, name_sim_val, addr_sim_val in rows
    ]


async def update_campaign_status(session: AsyncSession, campaign_id: str, donor_id: str, status: str) -> dict:
    campaign_uuid = _parse_uuid(campaign_id)
    if campaign_uuid is None:
        return {"ok": False, "error": "invalid campaign_id"}

    campaign = await session.get(Campaign, campaign_uuid)
    if campaign is None:
        return {"ok": False, "error": "campaign not found"}

    campaign.status = status
    await session.commit()
    return {"ok": True, "campaign_id": campaign_id, "donor_id": donor_id, "status": status}
