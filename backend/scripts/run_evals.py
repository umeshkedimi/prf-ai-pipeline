"""Runs the evaluation suites and reports scored results.

Deliberately a standalone CLI rather than pytest: evals are not pass/fail gates,
they're measurements you track. Nothing here exits non-zero for a low score —
you compare against the committed baseline and decide.

Usage:
  uv run python scripts/run_evals.py                          # default (cheap) suites
  uv run python scripts/run_evals.py --suite retrieval        # one suite
  uv run python scripts/run_evals.py --case adoption-story    # one case
  uv run python scripts/run_evals.py --include-expensive      # add trajectory
  uv run python scripts/run_evals.py --runs 5 --set-baseline  # record a new baseline
  uv run python scripts/run_evals.py --llm-model <cheap-id>   # sweep on a cheap model

Requires the stack up (postgres, mcp-crm, mcp-address), the DB seeded, and the
knowledge corpus ingested.
"""

import argparse
import asyncio

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import reset_engine
from app.evals.report import load_baseline, promote_to_baseline, render_console, write_latest
from app.evals.runner import run_suite
from app.evals.store import persist
from app.evals.suites import ALL_SUITES, resolve, select_cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PRF AI Pipeline evaluation suites.")
    parser.add_argument(
        "--suite",
        action="append",
        dest="suites",
        help=f"suite to run (repeatable). available: {', '.join(ALL_SUITES)}",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help="case id to run (repeatable). without this the whole suite runs.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=None,
        help="repeats per case (default 3, or the suite's own default). "
        ">1 is what surfaces model non-determinism.",
    )
    parser.add_argument(
        "--llm-model",
        help="override LLM_MODEL for this run, so a sweep can iterate on a cheap "
        "model and validate on the real one. Recorded in the results.",
    )
    parser.add_argument(
        "--include-expensive",
        action="store_true",
        help="also run expensive suites (full-pipeline trajectory sweeps)",
    )
    parser.add_argument(
        "--set-baseline",
        action="store_true",
        help="promote this run's scores to baseline.json (refused if the run had errors)",
    )
    parser.add_argument(
        "--force-baseline",
        action="store_true",
        help="promote to baseline even if the run had errors (you almost never want this)",
    )
    parser.add_argument("--no-db", action="store_true", help="skip persisting results to Postgres")
    return parser.parse_args()


async def main() -> None:
    configure_logging()
    args = parse_args()
    suites = select_cases(resolve(args.suites, args.include_expensive), args.cases)

    if args.cases and args.set_baseline:
        # promote_to_baseline replaces a suite's entry wholesale, so baselining
        # a filtered run would silently erase every case that didn't run.
        raise SystemExit("--case cannot be combined with --set-baseline: a filtered run would\n"
                         "replace the suite's baseline with only the cases you selected.")

    if args.llm_model:
        # get_settings is lru_cached, so mutating the cached instance is what
        # every downstream get_llm() call and the recorded result both read.
        get_settings().llm_model = args.llm_model
        print(f"overriding llm model for this run: {args.llm_model}")

    await reset_engine()
    try:
        reports = []
        for suite in suites:
            runs = args.runs if args.runs is not None else (suite.default_runs or 3)
            print(f"running {suite.name} ({len(suite.cases)} cases × {runs} runs)...")
            report = await run_suite(suite, runs_per_case=runs)
            reports.append(report)
            if not args.no_db:
                await persist(report)

        print(render_console(reports, baseline=load_baseline()))

        latest = write_latest(reports)
        print(f"  wrote {latest}")

        if args.set_baseline:
            # A run that hit errors (an exhausted API balance, a dead MCP server)
            # scores those cases 0.0. Recording that as the baseline bakes a
            # fake regression into every future comparison — the precise class
            # of confidently-wrong number this framework exists to prevent.
            broken = [
                (r.suite, len(r.errors), len(r.scorer_errors))
                for r in reports
                if r.errors or r.scorer_errors
            ]
            if broken and not args.force_baseline:
                print("\n  ✗ REFUSING to set baseline — this run had failures:")
                for suite, errors, scorer_errors in broken:
                    print(f"      {suite}: {errors} execution error(s), {scorer_errors} scorer error(s)")
                print("      Those cases scored 0.0 because they never ran, not because the")
                print("      system got them wrong. Fix the cause and re-run, or pass")
                print("      --force-baseline if you genuinely mean to record this.")
            else:
                baseline = promote_to_baseline(reports)
                print(f"  baseline updated: {baseline}")
    finally:
        await reset_engine()


if __name__ == "__main__":
    asyncio.run(main())
