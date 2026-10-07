import json

from app.evals import report as report_mod
from app.evals.types import SuiteReport


def _rep(name):
    return SuiteReport(suite=name, description="d", runs_per_case=1, case_count=1, duration_s=0.1)


def test_a_partial_promotion_stamps_only_the_suites_it_measured(tmp_path, monkeypatch):
    monkeypatch.setattr(report_mod, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(report_mod, "BASELINE_PATH", tmp_path / "baseline.json")
    monkeypatch.setattr(report_mod, "current_git_sha", lambda: "aaa111")
    monkeypatch.setattr(report_mod, "current_models", lambda: {"llm_model": "m", "judge_model": "j"})
    report_mod.promote_to_baseline([_rep("retrieval"), _rep("compliance")])

    monkeypatch.setattr(report_mod, "current_git_sha", lambda: "bbb222")
    report_mod.promote_to_baseline([_rep("campaign_agent")])

    data = json.loads((tmp_path / "baseline.json").read_text())
    assert data["suites"]["retrieval"]["git_sha"] == "aaa111"  # not re-credited to bbb222
    assert data["suites"]["compliance"]["git_sha"] == "aaa111"
    assert data["suites"]["campaign_agent"]["git_sha"] == "bbb222"
    assert data["git_sha"] == "bbb222"  # last write
