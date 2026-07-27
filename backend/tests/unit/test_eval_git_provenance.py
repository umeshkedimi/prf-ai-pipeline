"""An eval score is only attributable if the SHA it records can reproduce it.

Sweeps are normally run mid-iteration, so `HEAD` alone silently credits the
last commit for results produced by uncommitted code. The committed baseline
is the standing proof: it reports `pdf_generation` metrics against a SHA whose
tree has no `pdf_generation` suite. These tests pin the `-dirty` marker that
makes that visible.
"""

import subprocess

from app.evals import store

SHA = "6ff529003e1949d43b8b011cef16efbb4dcaa984"


def _fake_git(monkeypatch, *, head=SHA, porcelain="", fail=False):
    def run(cmd, **kwargs):
        if fail:
            raise subprocess.SubprocessError("git exploded")
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{head}\n", stderr="")
        if cmd[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=porcelain, stderr="")
        raise AssertionError(f"unexpected git call: {cmd}")

    monkeypatch.setattr(store.subprocess, "run", run)


def test_clean_tree_records_the_bare_sha(monkeypatch):
    _fake_git(monkeypatch, porcelain="")
    assert store.current_git_sha() == SHA


def test_dirty_tree_is_marked_rather_than_credited_to_head(monkeypatch):
    _fake_git(monkeypatch, porcelain=" M backend/src/app/evals/suites/pdf_generation.py\n")
    assert store.current_git_sha() == f"{SHA}-dirty"


def test_untracked_files_alone_do_not_count_as_dirty(monkeypatch):
    """`--untracked-files=no` is deliberate: scratch files say nothing about
    whether the evaluated code differs from the commit."""
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{SHA}\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(store.subprocess, "run", run)
    assert store.current_git_sha() == SHA
    assert ["git", "status", "--porcelain", "--untracked-files=no"] in calls


def test_missing_git_still_returns_none_rather_than_raising(monkeypatch):
    _fake_git(monkeypatch, fail=True)
    assert store.current_git_sha() is None


def test_dirty_check_failure_degrades_to_the_plain_sha(monkeypatch):
    """A broken `git status` must not take down a sweep that otherwise ran fine."""

    def run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{SHA}\n", stderr="")
        raise subprocess.SubprocessError("status failed")

    monkeypatch.setattr(store.subprocess, "run", run)
    assert store.current_git_sha() == SHA
