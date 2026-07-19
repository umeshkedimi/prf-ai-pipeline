"""Persists eval results to Postgres so metric history is queryable."""

import subprocess

from app.core.logging import get_logger
from app.db.models import EvalRun
from app.db.session import db_session
from app.evals.types import SuiteReport

log = get_logger(__name__)


def current_git_sha() -> str | None:
    """Ties a score to the code that produced it — without this a trend line is
    just a list of numbers with no way to attribute a regression."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True
        )
        return result.stdout.strip() or None
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


async def persist(report: SuiteReport) -> None:
    async with db_session() as session:
        session.add(
            EvalRun(
                suite=report.suite,
                git_sha=current_git_sha(),
                runs_per_case=report.runs_per_case,
                case_count=report.case_count,
                duration_s=report.duration_s,
                report=report.to_dict(),
            )
        )
        await session.commit()
    log.info("eval.persisted", suite=report.suite)
