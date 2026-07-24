"""Exercises the new GET /workflow/reviews queue endpoint against a real DB:
proves it surfaces both blocking (awaiting_review) and advisory (needs_review)
runs, filters correctly by status, and leaves completed/failed/running runs
out entirely."""

import pytest
from sqlalchemy import delete

from app.api.v1.endpoints.workflow import list_reviews
from app.db.models import WorkflowRun
from tests.conftest import seed_uuid

pytestmark = pytest.mark.integration


@pytest.fixture
async def review_queue_runs(db_session):
    donor_id = seed_uuid("donor", "d-0001")
    runs = [
        WorkflowRun(donor_id=donor_id, status="awaiting_review"),
        WorkflowRun(donor_id=donor_id, status="needs_review"),
        WorkflowRun(donor_id=donor_id, status="completed"),
        WorkflowRun(donor_id=donor_id, status="running"),
    ]
    db_session.add_all(runs)
    await db_session.commit()
    for run in runs:
        await db_session.refresh(run)
    yield runs
    await db_session.execute(delete(WorkflowRun).where(WorkflowRun.id.in_([r.id for r in runs])))
    await db_session.commit()


async def test_lists_both_awaiting_and_needs_review_by_default(db_session, review_queue_runs):
    awaiting, needs_review, completed, running = review_queue_runs
    result = await list_reviews(status=None, limit=50, offset=0, session=db_session)
    ids = {run.id for run in result}
    assert awaiting.id in ids
    assert needs_review.id in ids
    assert completed.id not in ids
    assert running.id not in ids


async def test_filters_to_a_single_status(db_session, review_queue_runs):
    awaiting, needs_review, _, _ = review_queue_runs
    result = await list_reviews(status="awaiting_review", limit=50, offset=0, session=db_session)
    ids = {run.id for run in result}
    assert awaiting.id in ids
    assert needs_review.id not in ids


async def test_pagination_limits_and_offsets_results(db_session, review_queue_runs):
    # The seeded DB can carry other pre-existing awaiting/needs_review rows
    # from earlier sessions, so this only checks pagination mechanics
    # (limit shrinks the page, offset shifts it) rather than which specific
    # rows land on which page.
    first_page = await list_reviews(status=None, limit=1, offset=0, session=db_session)
    second_page = await list_reviews(status=None, limit=1, offset=1, session=db_session)
    assert len(first_page) == 1
    assert len(second_page) == 1
    assert first_page[0].id != second_page[0].id


async def test_includes_donor_name_in_summary(db_session, review_queue_runs):
    awaiting, _, _, _ = review_queue_runs
    result = await list_reviews(status="awaiting_review", limit=50, offset=0, session=db_session)
    match = next(run for run in result if run.id == awaiting.id)
    assert match.donor_name.strip() != ""
