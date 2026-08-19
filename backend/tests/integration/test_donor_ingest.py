"""Exercises the CSV upsert logic against a real DB: new donors are
inserted, an existing donor (matched by external_id) is updated in place
rather than duplicated, a blank cell on update doesn't erase existing data,
and a row missing an identity field is rejected without touching the DB."""

import uuid

import pytest
from sqlalchemy import delete, select

from app.db.models import Donor
from app.donors.csv_ingest import ingest_donors

pytestmark = pytest.mark.integration

_TEST_EXTERNAL_ID = f"csv-test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def cleanup_donor(db_session):
    yield
    await db_session.execute(delete(Donor).where(Donor.external_id == _TEST_EXTERNAL_ID))
    await db_session.commit()


async def test_inserts_a_new_donor(db_session, cleanup_donor):
    rows = [
        {
            "external_id": _TEST_EXTERNAL_ID,
            "first_name": "Ada",
            "last_name": "Lovelace",
            "city": "London",
            "state": "NY",
        }
    ]
    result = await ingest_donors(db_session, rows)
    await db_session.commit()

    assert result == {"inserted": 1, "updated": 0, "rejected": []}
    donor = (
        await db_session.execute(select(Donor).where(Donor.external_id == _TEST_EXTERNAL_ID))
    ).scalars().first()
    assert donor is not None
    assert donor.first_name == "Ada"
    assert donor.city == "London"


async def test_updates_an_existing_donor_by_external_id_instead_of_duplicating(db_session, cleanup_donor):
    await ingest_donors(
        db_session, [{"external_id": _TEST_EXTERNAL_ID, "first_name": "Ada", "last_name": "Lovelace"}]
    )
    await db_session.commit()

    result = await ingest_donors(
        db_session,
        [{"external_id": _TEST_EXTERNAL_ID, "first_name": "Ada", "last_name": "King", "city": "London"}],
    )
    await db_session.commit()

    assert result == {"inserted": 0, "updated": 1, "rejected": []}
    donors = (
        (await db_session.execute(select(Donor).where(Donor.external_id == _TEST_EXTERNAL_ID)))
        .scalars()
        .all()
    )
    assert len(donors) == 1
    assert donors[0].last_name == "King"
    assert donors[0].city == "London"


async def test_a_blank_cell_on_update_does_not_erase_existing_data(db_session, cleanup_donor):
    await ingest_donors(
        db_session,
        [
            {
                "external_id": _TEST_EXTERNAL_ID,
                "first_name": "Ada",
                "last_name": "Lovelace",
                "city": "London",
            }
        ],
    )
    await db_session.commit()

    await ingest_donors(
        db_session,
        [{"external_id": _TEST_EXTERNAL_ID, "first_name": "Ada", "last_name": "Lovelace", "city": ""}],
    )
    await db_session.commit()

    donor = (
        await db_session.execute(select(Donor).where(Donor.external_id == _TEST_EXTERNAL_ID))
    ).scalars().first()
    assert donor.city == "London"


async def test_rejects_a_row_missing_an_identity_field_without_writing_it(db_session, cleanup_donor):
    result = await ingest_donors(
        db_session, [{"external_id": _TEST_EXTERNAL_ID, "first_name": "", "last_name": "Lovelace"}]
    )
    await db_session.commit()

    assert result["inserted"] == 0
    assert result["rejected"] == [
        {"row_number": 1, "reason": "missing required field 'first_name'", "external_id": _TEST_EXTERNAL_ID}
    ]
    donor = (
        await db_session.execute(select(Donor).where(Donor.external_id == _TEST_EXTERNAL_ID))
    ).scalars().first()
    assert donor is None
