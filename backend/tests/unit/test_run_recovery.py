"""Pure/mocked tests for stalled-run recovery: input selection, the heartbeat
wrapper, and that a failing heartbeat can never fail a node."""

from langgraph.types import Command

from app.graph import tracing
from app.workers.tasks import pick_graph_input

INITIAL = {"workflow_run_id": "r", "donor_id": "d", "campaign_id": None}


def test_a_review_decision_always_wins():
    cmd = Command(resume={"action": "approve"})
    assert pick_graph_input(cmd, False, None, INITIAL) is cmd
    assert pick_graph_input(cmd, True, {"x": 1}, INITIAL) is cmd


def test_a_fresh_run_starts_from_the_initial_input():
    assert pick_graph_input(None, False, None, INITIAL) == INITIAL


def test_a_recovered_run_continues_from_its_checkpoint():
    # input None is how LangGraph continues from the saved checkpoint
    assert pick_graph_input(None, True, {"donor_profile": {}}, INITIAL) is None


def test_a_recovered_run_with_no_checkpoint_starts_fresh():
    """The worker died before the first checkpoint was written."""
    assert pick_graph_input(None, True, {}, INITIAL) == INITIAL
    assert pick_graph_input(None, True, None, INITIAL) == INITIAL


async def test_traced_node_stamps_the_heartbeat_before_the_node_runs(monkeypatch):
    order: list[str] = []

    async def fake_touch(run_id):
        order.append(f"heartbeat:{run_id}")

    async def node(state):
        order.append("node")
        return {"x": 1}

    monkeypatch.setattr(tracing, "touch_heartbeat", fake_touch)
    result = await tracing.traced_node("n", node)({"workflow_run_id": "run-1"})

    assert result == {"x": 1}
    assert order == ["heartbeat:run-1", "node"]


async def test_a_failing_heartbeat_write_never_fails_the_node(monkeypatch):
    from app.workers import run_recovery

    class BoomSession:
        async def __aenter__(self):
            raise ConnectionError("db down")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(run_recovery, "db_session", lambda: BoomSession())
    await run_recovery.touch_heartbeat("00000000-0000-0000-0000-000000000001")  # must not raise


async def test_no_run_id_is_a_no_op():
    from app.workers import run_recovery

    await run_recovery.touch_heartbeat(None)
    await run_recovery.touch_heartbeat("")
