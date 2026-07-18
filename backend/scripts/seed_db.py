"""Idempotently seeds demo campaigns, donors, and donations for local development.

Usage: uv run python scripts/seed_db.py
"""

import asyncio
import uuid
from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import Campaign, Donation, Donor, SuppressionListEntry
from app.db.session import db_session

# Fixed namespace so donor_id/campaign_id/donation_id are stable across re-runs.
NAMESPACE = uuid.UUID("6f9c3b1a-9b0e-4c9a-9c2e-9d6a2b6b8a10")


def _uuid(*parts: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, ":".join(parts))


CAMPAIGNS = [
    {"name": "2026 Spring Appeal", "appeal_code": "SPRING26", "status": "active"},
    {"name": "Year-End Giving", "appeal_code": "YEG25", "status": "completed"},
    {"name": "Major Gifts Initiative", "appeal_code": "MGI", "status": "active"},
]

# d-0001 through d-0008: one donor per Donor Verification scenario (clean, duplicate
# pair, do-not-contact, suppressed/deceased, suspicious, malformed/missing contact info).
# d-0009/d-0010 (Phase 2): Address Intelligence scenarios not covered above.
DONORS = [
    {
        "external_id": "d-0001",
        "first_name": "Eleanor",
        "last_name": "Whitfield",
        "email": "eleanor.whitfield@example.com",
        "address_line1": "123 Maple St",
        "city": "Springfield",
        "state": "IL",
        "postal_code": "62704",
        "do_not_contact": False,
        "notes": "clean, eligible donor",
        "campaign": "2026 Spring Appeal",
        "donations": [(150.00, date(2026, 2, 14))],
    },
    {
        "external_id": "d-0002",
        "first_name": "Robert",
        "last_name": "Hendricks",
        "email": "rhendricks@example.com",
        "address_line1": "456 Oak Avenue Apt 2",
        "city": "Madison",
        "state": "WI",
        "postal_code": "53703",
        "do_not_contact": False,
        "notes": "duplicate pair member A",
        "campaign": "Year-End Giving",
        "donations": [(75.00, date(2025, 11, 3))],
    },
    {
        "external_id": "d-0003",
        "first_name": "Bob",
        "last_name": "Hendricks",
        "email": "bob.hendricks@example.com",
        "address_line1": "456 Oak Ave #2",
        "city": "Madison",
        "state": "WI",
        "postal_code": "53703",
        "do_not_contact": False,
        "notes": "duplicate pair member B - same person as d-0002",
        "campaign": "Year-End Giving",
        "donations": [(75.00, date(2025, 11, 3))],
    },
    {
        "external_id": "d-0004",
        "first_name": "Margaret",
        "last_name": "Sullivan",
        "email": "msullivan@example.com",
        "address_line1": "789 Birch Lane",
        "city": "Austin",
        "state": "TX",
        "postal_code": "78701",
        "do_not_contact": True,
        "notes": "opted out - do_not_contact",
        "campaign": "Major Gifts Initiative",
        "donations": [(40.00, date(2024, 6, 1))],
    },
    {
        "external_id": "d-0005",
        "first_name": "Harold",
        "last_name": "Voss",
        "email": "hvoss@example.com",
        "address_line1": "22 River Rd",
        "city": "Portland",
        "state": "OR",
        "postal_code": "97201",
        "do_not_contact": False,
        "notes": "on suppression list (deceased)",
        "campaign": "Major Gifts Initiative",
        "donations": [(200.00, date(2023, 9, 12))],
        "suppression_reason": "deceased",
    },
    {
        "external_id": "d-0006",
        "first_name": "Gerald",
        "last_name": "Kowalski",
        "email": "gkowalski@example.com",
        "address_line1": "PO Box 9911",
        "city": "Reno",
        "state": "NV",
        "postal_code": "89501",
        "do_not_contact": False,
        "notes": "suspicious: PO box address + donation far above historical pattern",
        "campaign": "Major Gifts Initiative",
        "donations": [
            (60.00, date(2024, 3, 1)),
            (75.00, date(2024, 9, 15)),
            (50000.00, date(2026, 1, 20)),
        ],
    },
    {
        "external_id": "d-0007",
        "first_name": "J.",
        "last_name": "Doe",
        "email": None,
        "address_line1": None,
        "city": None,
        "state": None,
        "postal_code": None,
        "do_not_contact": False,
        "notes": "malformed record: missing address/email",
        "campaign": "2026 Spring Appeal",
        "donations": [(10.00, date(2026, 3, 1))],
    },
    {
        "external_id": "d-0008",
        "first_name": "Priya",
        "last_name": "Raman",
        "email": "priya.raman@example.com",
        "address_line1": "50 Elm Ct",
        "city": "Seattle",
        "state": "WA",
        "postal_code": "98101",
        "do_not_contact": False,
        "notes": "clean, recurring small-dollar donor",
        "campaign": "2026 Spring Appeal",
        "donations": [(20.00, date(2025, 9, 10)), (25.00, date(2026, 3, 10))],
    },
    # Phase 2 additions: eligible per Donor Verification, but each exercises a
    # distinct Address Intelligence branch not covered by d-0001 through d-0008.
    {
        "external_id": "d-0009",
        "first_name": "Nathaniel",
        "last_name": "Cross",
        "email": "nathaniel.cross@example.com",
        "address_line1": "410 Willow St",
        "city": "Denver",
        "state": "CO",
        "postal_code": "80203",
        "do_not_contact": False,
        "notes": "New annual donor; onboarded via a community outreach event.",
        "campaign": "2026 Spring Appeal",
        "donations": [(50.00, date(2025, 8, 4))],
    },
    {
        "external_id": "d-0010",
        "first_name": "Carla",
        "last_name": "Jennings",
        "email": "carla.jennings@example.com",
        "address_line1": "999 Ghost Ave",
        "city": "Detroit",
        "state": "MI",
        "postal_code": "48201",
        "do_not_contact": False,
        "notes": "First-time donor; contact info collected at a fundraising gala.",
        "campaign": "Year-End Giving",
        "donations": [(35.00, date(2025, 10, 22))],
    },
]


async def seed() -> None:
    async with db_session() as session:
        campaign_ids: dict[str, uuid.UUID] = {}
        for c in CAMPAIGNS:
            cid = _uuid("campaign", c["name"])
            campaign_ids[c["name"]] = cid
            stmt = pg_insert(Campaign).values(
                id=cid, name=c["name"], appeal_code=c["appeal_code"], status=c["status"]
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[Campaign.id],
                set_={"appeal_code": stmt.excluded.appeal_code, "status": stmt.excluded.status},
            )
            await session.execute(stmt)

        for d in DONORS:
            donor_id = _uuid("donor", d["external_id"])
            stmt = pg_insert(Donor).values(
                id=donor_id,
                external_id=d["external_id"],
                first_name=d["first_name"],
                last_name=d["last_name"],
                email=d["email"],
                address_line1=d["address_line1"],
                city=d["city"],
                state=d["state"],
                postal_code=d["postal_code"],
                do_not_contact=d["do_not_contact"],
                notes=d["notes"],
            )
            update_cols = {
                col: stmt.excluded[col]
                for col in (
                    "first_name",
                    "last_name",
                    "email",
                    "address_line1",
                    "city",
                    "state",
                    "postal_code",
                    "do_not_contact",
                    "notes",
                )
            }
            stmt = stmt.on_conflict_do_update(index_elements=[Donor.id], set_=update_cols)
            await session.execute(stmt)

            campaign_id = campaign_ids[d["campaign"]]
            for i, (amount, donation_date) in enumerate(d["donations"]):
                donation_id = _uuid("donation", d["external_id"], str(i))
                stmt = pg_insert(Donation).values(
                    id=donation_id,
                    donor_id=donor_id,
                    campaign_id=campaign_id,
                    amount=amount,
                    donation_date=donation_date,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[Donation.id],
                    set_={"amount": stmt.excluded.amount, "donation_date": stmt.excluded.donation_date},
                )
                await session.execute(stmt)

            if reason := d.get("suppression_reason"):
                supp_id = _uuid("suppression", d["external_id"])
                stmt = pg_insert(SuppressionListEntry).values(
                    id=supp_id,
                    donor_id=donor_id,
                    email=d["email"],
                    reason=reason,
                    source="seed_data",
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[SuppressionListEntry.id], set_={"reason": stmt.excluded.reason}
                )
                await session.execute(stmt)

        await session.commit()

    print(f"Seeded {len(CAMPAIGNS)} campaigns and {len(DONORS)} donors.")


if __name__ == "__main__":
    asyncio.run(seed())
