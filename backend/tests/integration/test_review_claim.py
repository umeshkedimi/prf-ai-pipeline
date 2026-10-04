"""POST /workflow/{id}/review against a real DB: the atomic claim and stage
binding that stop two reviewers acting on the same pause."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from app.api.v1.endpoints import workflow as endpoint
from app.db.models import WorkflowRun
from app.schemas.workflow import ReviewDecisionCreate
from tests.conftest import seed_uuid

pytestmark = pytest.mark.integration

REVIEWER_A = SimpleNamespace(email="a@prf.local")
REVIEWER_B = SimpleNamespace(email="b@prf.local")


@pytest.fixture
async def paused_run(db_session):
    run = WorkflowRun(
        donor_id=seed_uuid("donor", "d-0001"),
        status="awaiting_review",
        pending_review={"stage": "address", "reason": "address_confidence_below_threshold"},
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    rid = run.id  # captured: attributes expire on every commit
    yield rid
    await db_session.rollback()
    await db_session.execute(delete(WorkflowRun).where(WorkflowRun.id == rid))
    await db_session.commit()


@pytest.fixture
def enqueued(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(endpoint.resume_workflow_after_review, "delay", lambda *a: calls.append(a))
    return calls


def _decision(stage="address", action="approve"):
    return ReviewDecisionCreate(action=action, stage=stage)


async def test_only_one_of_two_reviewers_wins_the_pause(db_session, paused_run, enqueued):
    await endpoint.submit_review(paused_run, _decision(), db_session, REVIEWER_A)
    assert len(enqueued) == 1
    assert enqueued[0][1]["reviewer"] == "a@prf.local"

    # B decides on the same pause a moment later: must lose, and must not enqueue.
    with pytest.raises(HTTPException) as exc:
        await endpoint.submit_review(paused_run, _decision(action="reject"), db_session, REVIEWER_B)
    assert exc.value.status_code == 409
    assert "already have decided" in exc.value.detail
    assert len(enqueued) == 1


async def test_a_decision_for_the_wrong_stage_is_refused(db_session, paused_run, enqueued):
    with pytest.raises(HTTPException) as exc:
        await endpoint.submit_review(paused_run, _decision(stage="recommendation"), db_session, REVIEWER_A)
    assert exc.value.status_code == 409
    assert "paused at stage 'address'" in exc.value.detail
    assert enqueued == []

    # A refused decision does not consume the pause: the right stage still works.
    await endpoint.submit_review(paused_run, _decision(stage="address"), db_session, REVIEWER_A)
    assert len(enqueued) == 1


async def test_a_run_that_is_not_paused_is_refused(db_session, enqueued):
    run = WorkflowRun(donor_id=seed_uuid("donor", "d-0001"), status="completed")
    db_session.add(run)
    await db_session.commit()
    rid = run.id
    try:
        with pytest.raises(HTTPException) as exc:
            await endpoint.submit_review(rid, _decision(), db_session, REVIEWER_A)
        assert exc.value.status_code == 409
        assert enqueued == []
    finally:
        await db_session.rollback()
        await db_session.execute(delete(WorkflowRun).where(WorkflowRun.id == rid))
        await db_session.commit()


async def test_unknown_run_is_404(db_session, enqueued):
    with pytest.raises(HTTPException) as exc:
        await endpoint.submit_review(uuid.uuid4(), _decision(), db_session, REVIEWER_A)
    assert exc.value.status_code == 404


async def test_enqueue_failure_gives_the_pause_back(db_session, paused_run, monkeypatch):
    def boom(*_):
        raise ConnectionError("broker down")

    monkeypatch.setattr(endpoint.resume_workflow_after_review, "delay", boom)
    with pytest.raises(HTTPException) as exc:
        await endpoint.submit_review(paused_run, _decision(), db_session, REVIEWER_A)
    assert exc.value.status_code == 503

    run = await db_session.get(WorkflowRun, paused_run)
    await db_session.refresh(run)
    assert run.status == "awaiting_review"  # not stranded in `running`
