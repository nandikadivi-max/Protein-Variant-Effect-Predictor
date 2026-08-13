"""
Tests for the percentile that ResultsService attaches to a single score.

These exercise the statistic through the same helper the service uses, with
no DB, no network and no matrix store, so they run in the fast suite.
"""

import numpy as np
import pytest

from api.services.results_service import _percentile_for, classify_llr
from contracts.schemas import EffectLabel
from domain.derive import Variant, full_effect_map, score_variant
from domain.scoring import AA_INDEX


def make_matrix(length: int, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(size=(length, 20)).astype(np.float32)


SEQ = "ACDEFGHIKLMNPQRSTVWY"


def test_single_substitution_gets_a_percentile() -> None:
    M = make_matrix(len(SEQ))
    effect_map = full_effect_map(M, SEQ)
    variant = Variant.parse("A1C")
    llr = score_variant(M, variant)

    pct = _percentile_for(variant, effect_map, SEQ, llr)
    assert pct is not None
    assert 0.0 <= pct <= 100.0


def test_multi_substitution_percentile_is_none() -> None:
    """
    score_variant SUMS substitution LLRs, so a multi-sub score is not drawn
    from the single-substitution pool. Reporting a rank there would claim a
    near-maximal percentile for any multi-sub variant, however mild.
    """
    M = make_matrix(len(SEQ))
    effect_map = full_effect_map(M, SEQ)
    variant = Variant.parse("A1C:D3E")
    llr = score_variant(M, variant)

    assert _percentile_for(variant, effect_map, SEQ, llr) is None


def test_multi_substitution_would_have_ranked_near_the_top() -> None:
    """
    Demonstrates why the gate exists rather than just asserting it does.

    Built so every single substitution scores exactly -2.0. Each one is
    therefore precisely median. A four-substitution variant sums to -8.0,
    which is off the bottom of that distribution entirely, so an ungated
    ranking would call it maximally damaging while every component of it is
    ordinary.
    """
    from domain.derive import llr_percentile

    M = np.full((len(SEQ), 20), -2.0, dtype=np.float32)
    for i, aa in enumerate(SEQ):
        M[i, AA_INDEX[aa]] = 0.0
    effect_map = full_effect_map(M, SEQ)

    single = score_variant(M, Variant.parse("A1C"))
    summed = score_variant(M, Variant.parse("A1C:D3E:F5G:H7I"))
    assert single == pytest.approx(-2.0)
    assert summed == pytest.approx(-8.0)

    assert llr_percentile(effect_map, SEQ, single) == pytest.approx(50.0)
    assert llr_percentile(effect_map, SEQ, summed) == pytest.approx(100.0)


def test_a_more_damaging_mutation_ranks_higher() -> None:
    """The direction of the statistic, pinned against a constructed matrix."""
    seq = "AAAA"
    effect_map = np.zeros((4, 20), dtype=np.float32)
    mask = np.ones((4, 20), dtype=bool)
    mask[:, AA_INDEX["A"]] = False
    effect_map[mask] = -2.0

    severe = _percentile_for(Variant.parse("A1C"), effect_map, seq, -8.0)
    mild = _percentile_for(Variant.parse("A1C"), effect_map, seq, -0.1)
    assert severe is not None and mild is not None
    assert severe > mild
    assert severe == pytest.approx(100.0)
    assert mild == pytest.approx(0.0)


def test_classify_llr_boundaries_unchanged() -> None:
    """Guards the calibrated thresholds against accidental drift."""
    assert classify_llr(-5.97) is EffectLabel.LIKELY_DAMAGING
    assert classify_llr(-0.098) is EffectLabel.LIKELY_TOLERATED
    assert classify_llr(-3.0) is EffectLabel.UNCERTAIN
