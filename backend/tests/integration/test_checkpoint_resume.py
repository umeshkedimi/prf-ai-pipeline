"""Proves LangGraph's Postgres checkpointer survives a genuine process crash:
drives scripts/run_workflow_cli.py as real subprocesses (the same tool a human
would run for the demo) rather than importing its internals, so this exercises
the actual CLI a reviewer would use.
"""

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models import AgentAuditLog
from app.db.models import WorkflowRun as WorkflowRunModel
from app.db.session import db_session
from tests.conftest import seed_uuid

pytestmark = pytest.mark.integration

CLI_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_workflow_cli.py"


async def _audit_steps(workflow_run_id: str) -> list[str]:
    async with db_session() as session:
        result = await session.execute(
            select(AgentAuditLog.step)
            .where(AgentAuditLog.workflow_run_id == uuid.UUID(workflow_run_id))
            .order_by(AgentAuditLog.created_at)
        )
        return list(result.scalars().all())


async def test_crash_after_gather_context_then_resume_does_not_rerun_completed_nodes():
    donor_uuid = seed_uuid("donor", "d-0001")
    async with db_session() as session:
        run = WorkflowRunModel(donor_id=donor_uuid)
        session.add(run)
        await session.commit()
        await session.refresh(run)
        workflow_run_id = str(run.id)

    crash_proc = subprocess.run(
        [sys.executable, str(CLI_SCRIPT), "_run_until_crash", "--workflow-run-id", workflow_run_id],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert crash_proc.returncode == 1, crash_proc.stderr  # a real hard exit, not a clean 0
    assert await _audit_steps(workflow_run_id) == ["fetch_core_data", "gather_context"]

    resume_proc = subprocess.run(
        [sys.executable, str(CLI_SCRIPT), "resume", "--workflow-run-id", workflow_run_id],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert resume_proc.returncode == 0, resume_proc.stderr
    verdict = json.loads(resume_proc.stdout)
    assert verdict["eligible"] is True

    # the operative claim: fetch_core_data and gather_context ran exactly once
    # each, before the crash — resume only added synthesize_verdict.
    assert await _audit_steps(workflow_run_id) == [
        "fetch_core_data",
        "gather_context",
        "synthesize_verdict",
    ]
