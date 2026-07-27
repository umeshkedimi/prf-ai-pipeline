"""Persists eval results to Postgres so metric history is queryable."""

import subprocess

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import EvalRun
from app.db.session import db_session
from app.evals.types import SuiteReport

log = get_logger(__name__)


def current_git_sha() -> str | None:
    """Ties a score to the code that produced it — without this a trend line is
    just a list of numbers with no way to attribute a regression.

    A bare `HEAD` is not enough: an eval sweep is usually run *while iterating*,
    so the code that actually produced the scores is the working tree, not the
    last commit. The committed baseline is the proof — it reports `pdf_generation`
    metrics against a SHA whose tree has no `pdf_generation` suite in it, because
    that sweep ran before the phase was committed. A `-dirty` suffix keeps the
    pointer honest about that rather than silently attributing scores to a commit
    that cannot reproduce them.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True
        )
        sha = result.stdout.strip()
        if not sha:
            return None
        return f"{sha}-dirty" if _working_tree_is_dirty() else sha
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def _working_tree_is_dirty() -> bool:
    """Tracked-file modifications only. Untracked files are ignored on purpose:
    scratch files and unignored artifacts sitting in the repo say nothing about
    whether the code under evaluation differs from the commit."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return bool(result.stdout.strip())
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def current_models() -> dict[str, str]:
    """The models a score was produced by. Without this, swapping provider or
    model reads as a code regression in the delta column — every metric moves
    at once and `git_sha` alone gives no way to tell why."""
    settings = get_settings()
    return {"llm_model": settings.llm_model, "judge_model": settings.judge_model}


async def persist(report: SuiteReport) -> None:
    models = current_models()
    async with db_session() as session:
        session.add(
            EvalRun(
                suite=report.suite,
                git_sha=current_git_sha(),
                llm_model=models["llm_model"],
                judge_model=models["judge_model"],
                runs_per_case=report.runs_per_case,
                case_count=report.case_count,
                duration_s=report.duration_s,
                report=report.to_dict(),
            )
        )
        await session.commit()
    log.info("eval.persisted", suite=report.suite)
