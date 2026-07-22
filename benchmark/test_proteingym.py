"""Unit tests for the ProteinGym harness. No torch, no network."""

import numpy as np

from benchmark.proteingym import score_assay, spearman


def test_spearman_perfect_positive():
    assert abs(spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1.0) < 1e-9


def test_spearman_perfect_negative():
    assert abs(spearman([1, 2, 3, 4], [40, 30, 20, 10]) + 1.0) < 1e-9


def test_spearman_degenerate_is_nan():
    r = spearman([5, 5, 5], [1, 2, 3])  # zero variance on x
    assert r != r  # nan


class _FakeScorer:
    model_id = "fake"

    def per_position_log_probs(self, sequence: str) -> np.ndarray:
        return np.random.default_rng(0).normal(size=(len(sequence), 20)).astype("float32")


def test_score_assay_skips_mismatched_and_invalid():
    seq = "MKV"
    rows = [
        {"mutant": "M1A", "DMS_score": "0.5", "DMS_score_bin": "1"},   # ok
        {"mutant": "K2D", "DMS_score": "-1.0", "DMS_score_bin": "0"},  # ok
        {"mutant": "X9Z", "DMS_score": "0.0", "DMS_score_bin": "0"},   # invalid AA / out of range
        {"mutant": "A1A", "DMS_score": "0.0", "DMS_score_bin": "0"},   # WT mismatch (pos 1 is M)
    ]
    res = score_assay(_FakeScorer(), "TEST", seq, rows)
    assert res.n_mutants == 4
    assert res.n_scored == 2
    assert {m.mutant for m in res.scored} == {"M1A", "K2D"}
    assert res.spearman == res.spearman or res.n_scored < 2  # a real float
