"""The model-drift warning exists because a delta against a baseline produced
by a different model compares two models, not two commits. These tests pin the
cases where staying silent would let the delta arrows imply a code regression.
"""

import pytest

from app.evals import report as report_module
from app.evals.report import _model_drift_warning

CURRENT = {"llm_model": "gemini-2.5-flash", "judge_model": "gemini-2.5-flash-lite"}


@pytest.fixture(autouse=True)
def _pin_current_models(monkeypatch):
    monkeypatch.setattr(report_module, "current_models", lambda: dict(CURRENT))


def test_no_warning_without_a_baseline():
    assert _model_drift_warning(None) == []


def test_no_warning_when_models_match():
    assert _model_drift_warning({**CURRENT, "suites": {}}) == []


def test_warns_when_the_pipeline_model_changed():
    lines = _model_drift_warning({**CURRENT, "llm_model": "claude-sonnet-5"})
    body = "\n".join(lines)
    assert "claude-sonnet-5 → gemini-2.5-flash" in body
    # The judge is unchanged here, so it must not be reported as drift.
    assert "judge model" not in body


def test_warns_when_only_the_judge_model_changed():
    lines = _model_drift_warning({**CURRENT, "judge_model": "claude-haiku-4-5-20251001"})
    body = "\n".join(lines)
    assert "claude-haiku-4-5-20251001 → gemini-2.5-flash-lite" in body
    assert "llm model" not in body


def test_pre_existing_baseline_without_model_fields_reads_as_unrecorded():
    """The committed baseline predates these fields. Absent must not be treated
    as a match — those numbers really did come from an unknown model."""
    lines = _model_drift_warning({"git_sha": "abc123", "suites": {}})
    body = "\n".join(lines)
    assert "unrecorded → gemini-2.5-flash" in body
    assert "unrecorded → gemini-2.5-flash-lite" in body


def test_build_payload_records_the_models_that_produced_the_scores():
    payload = report_module.build_payload([])
    assert payload["llm_model"] == CURRENT["llm_model"]
    assert payload["judge_model"] == CURRENT["judge_model"]
