"""POST /workflow/{id}/release against a real DB: the atomic claim (a second
request must not place a second order), discard, enqueue failure rollback,
and the release task's success and failure paths."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.api.v1.endpoints import workflow as endpoint
from app.db.models import AgentAuditLog, WorkflowRun
from app.schemas.workflow import HeldLetterDecision
from app.workers import tasks
from tests.conftest import seed_uuid

pytestmark = pytest.mark.integration

USER = SimpleNamespace(email="reviewer@prf.local")
HELD_PDF = {"reference": "PRF-HELD0001", "page_count": 1, "held": True, "hold_reason": ["bad wording"]}


@pytest.fixture
async def held_run(db_session):
    run = WorkflowRun(
        donor_id=seed_uuid("donor", "d-0001"),
        status="needs_review",
        result={"pdf_generation": dict(HELD_PDF)},
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    rid = run.id  # captured: attributes expire on every commit
    yield run
    await db_session.rollback()
    await db_session.execute(delete(AgentAuditLog).where(AgentAuditLog.workflow_run_id == rid))
    await db_session.execute(delete(WorkflowRun).where(WorkflowRun.id == rid))
    await db_session.commit()


@pytest.fixture
def enqueued(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(endpoint.release_held_letter, "delay", lambda *a: calls.append(a))
    return calls


def _decision(action="release"):
    return HeldLetterDecision(action=action, notes="reviewed the wording manually")


async def test_release_claims_the_run_and_enqueues_once(db_session, held_run, enqueued):
    rid = held_run.id
    await endpoint.release_held(rid, _decision(), db_session, USER)
    assert len(enqueued) == 1
    assert enqueued[0][1]["reviewer"] == "reviewer@prf.local"  # from the session

    # A second request must lose the claim: no second order.
    with pytest.raises(HTTPException) as exc:
        await endpoint.release_held(rid, _decision(), db_session, USER)
    assert exc.value.status_code == 409
    assert len(enqueued) == 1


async def test_a_needs_review_run_with_no_held_letter_is_rejected(db_session, enqueued):
    run = WorkflowRun(
        donor_id=seed_uuid("donor", "d-0001"),
        status="needs_review",
        result={"pdf_generation": {"held": False}},
    )
    db_session.add(run)
    await db_session.commit()
    rid = run.id
    try:
        with pytest.raises(HTTPException) as exc:
            await endpoint.release_held(rid, _decision(), db_session, USER)
        assert exc.value.status_code == 409
        assert enqueued == []
    finally:
        await db_session.rollback()
        await db_session.execute(delete(WorkflowRun).where(WorkflowRun.id == rid))
        await db_session.commit()


async def test_unknown_run_is_404(db_session, enqueued):
    import uuid

    with pytest.raises(HTTPException) as exc:
        await endpoint.release_held(uuid.uuid4(), _decision(), db_session, USER)
    assert exc.value.status_code == 404


async def test_discard_closes_the_run_without_enqueuing(db_session, held_run, enqueued):
    rid = held_run.id
    run = await endpoint.release_held(rid, _decision("discard"), db_session, USER)
    assert run.status == "discarded"
    assert run.result["pdf_generation"]["discarded_by"] == "reviewer@prf.local"
    assert enqueued == []
    rows = (
        await db_session.execute(
            select(AgentAuditLog).where(AgentAuditLog.workflow_run_id == rid)
        )
    ).scalars().all()
    assert [r.step for r in rows] == ["discard_held_letter"]
    assert rows[0].agent_name == "human_review"  # so it shows in review_history
    assert rows[0].source_refs[0]["action"] == "discard"


async def test_enqueue_failure_rolls_the_claim_back(db_session, held_run, monkeypatch):
    rid = held_run.id
    def boom(*_):
        raise ConnectionError("broker down")

    monkeypatch.setattr(endpoint.release_held_letter, "delay", boom)
    with pytest.raises(HTTPException) as exc:
        await endpoint.release_held(rid, _decision(), db_session, USER)
    assert exc.value.status_code == 503
    await db_session.refresh(held_run)
    assert held_run.status == "needs_review"  # not stranded in `running`


async def test_release_task_places_the_order_and_completes_the_run(db_session, held_run, monkeypatch):
    rid = held_run.id
    async def fake_submit(reference, page_count):
        return {"vendor_order_id": "PV-X", "tracking_number": "94"}, [{"tool_name": "submit_print_order"}]

    monkeypatch.setattr(tasks, "submit_print_order", fake_submit)
    held_run.status = "running"  # as the endpoint's claim leaves it
    await db_session.commit()

    await tasks._release(
        str(rid), {"action": "release", "notes": "fine", "reviewer": "reviewer@prf.local"}
    )

    await db_session.refresh(held_run)
    pdf = held_run.result["pdf_generation"]
    assert held_run.status == "completed"
    assert pdf["held"] is False and pdf["vendor_order_id"] == "PV-X"
    assert pdf["released_by"] == "reviewer@prf.local"
    rows = (
        await db_session.execute(
            select(AgentAuditLog).where(AgentAuditLog.workflow_run_id == rid)
        )
    ).scalars().all()
    assert rows[0].step == "release_held_letter" and rows[0].source_refs[0]["action"] == "release"


async def test_release_task_failure_returns_the_run_to_needs_review(db_session, held_run, monkeypatch):
    rid = held_run.id
    async def failing_submit(reference, page_count):
        raise RuntimeError("vendor unavailable")

    monkeypatch.setattr(tasks, "submit_print_order", failing_submit)
    held_run.status = "running"
    await db_session.commit()

    with pytest.raises(RuntimeError):
        await tasks._release(str(rid), {"notes": "fine", "reviewer": "r@prf.local"})

    await db_session.refresh(held_run)
    assert held_run.status == "needs_review"
    assert "vendor unavailable" in held_run.error
    assert held_run.result["pdf_generation"]["held"] is True  # still held, no order
