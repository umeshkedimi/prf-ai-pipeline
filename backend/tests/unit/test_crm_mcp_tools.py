"""Exercises the CRM MCP server's query layer directly against the real seeded
Postgres database (no LLM, no MCP transport) — requires `docker compose up -d
postgres` and `python scripts/seed_db.py` to have been run first.
"""

import pytest

from app.mcp_servers.crm import queries
from tests.conftest import seed_uuid

pytestmark = pytest.mark.integration


async def test_get_donor_profile_clean_donor(db_session):
    donor_id = str(seed_uuid("donor", "d-0001"))
    profile = await queries.get_donor_profile(db_session, donor_id)

    assert profile is not None
    assert profile.first_name == "Eleanor"
    assert profile.do_not_contact is False
    assert profile.is_suppressed is False


async def test_get_donor_profile_do_not_contact(db_session):
    donor_id = str(seed_uuid("donor", "d-0004"))
    profile = await queries.get_donor_profile(db_session, donor_id)

    assert profile is not None
    assert profile.do_not_contact is True


async def test_get_donor_profile_suppressed(db_session):
    donor_id = str(seed_uuid("donor", "d-0005"))
    profile = await queries.get_donor_profile(db_session, donor_id)

    assert profile is not None
    assert profile.is_suppressed is True
    assert profile.suppression_reason == "deceased"


async def test_get_donor_profile_not_found(db_session):
    profile = await queries.get_donor_profile(db_session, str(seed_uuid("donor", "does-not-exist")))
    assert profile is None


async def test_get_donation_history_suspicious_donor(db_session):
    donor_id = str(seed_uuid("donor", "d-0006"))
    history = await queries.get_donation_history(db_session, donor_id)

    assert len(history) == 3
    amounts = sorted(record.amount for record in history)
    assert amounts == [60.0, 75.0, 50000.0]
    # most recent first
    assert history[0].amount == 50000.0


async def test_find_potential_duplicate_donors_matches_pair(db_session):
    d0002 = str(seed_uuid("donor", "d-0002"))
    d0003 = str(seed_uuid("donor", "d-0003"))

    candidates = await queries.find_potential_duplicate_donors(
        db_session,
        name="Robert Hendricks",
        address="456 Oak Avenue Apt 2",
        exclude_donor_id=d0002,
    )

    assert len(candidates) >= 1
    top = candidates[0]
    assert top.donor_id == d0003
    assert top.name_similarity > 0.3
    assert top.address_similarity > 0.3


async def test_find_potential_duplicate_donors_no_match(db_session):
    candidates = await queries.find_potential_duplicate_donors(
        db_session,
        name="Zzyzx Qwerty",
        address="0 Nowhere Rd",
        exclude_donor_id=str(seed_uuid("donor", "d-0001")),
    )
    assert candidates == []


async def test_update_campaign_status_roundtrip(db_session):
    campaign_id = str(seed_uuid("campaign", "Year-End Giving"))
    donor_id = str(seed_uuid("donor", "d-0002"))

    result = await queries.update_campaign_status(db_session, campaign_id, donor_id, "letters_mailed")
    assert result["ok"] is True
    assert result["status"] == "letters_mailed"

    # restore original seed value so re-running the suite / seed script stays consistent
    revert = await queries.update_campaign_status(db_session, campaign_id, donor_id, "completed")
    assert revert["ok"] is True


async def test_update_campaign_status_invalid_id(db_session):
    result = await queries.update_campaign_status(db_session, "not-a-uuid", "irrelevant", "completed")
    assert result["ok"] is False
