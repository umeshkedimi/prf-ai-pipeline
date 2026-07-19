"""Evaluation framework.

Tests answer "does the code do what I wrote?" — deterministic, binary, permanent.
Evals answer "does the system make good decisions?" — probabilistic, scored, and
re-measured on every prompt or model change. Nothing here raises on a bad result;
it reports a number you track against a committed baseline.
"""
