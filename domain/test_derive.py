import numpy as np
import pytest

from domain.derive import (
    Substitution,
    Variant,
    full_effect_map,
    llr_percentile,
    per_residue_impact,
    score_substitution,
    score_variant,
    substitution_llrs,
    validate_against_sequence,
)
from domain.scoring import AA_INDEX


def make_fake_matrix(length: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(size=(length, 20)).astype(np.float32)


def test_variant_parse_single():
    v = Variant.parse("R248Q")
    assert len(v.substitutions) == 1
    assert v.substitutions[0] == Substitution(248, "R", "Q")
    assert str(v) == "R248Q"


def test_variant_parse_multi():
    v = Variant.parse("R248Q:D281N")
    assert len(v.substitutions) == 2
    assert str(v) == "R248Q:D281N"


def test_variant_parse_rejects_malformed():
    with pytest.raises(ValueError):
        Variant.parse("garbage")
    with pytest.raises(ValueError):
        Variant.parse("Z1A")  # Z not a canonical residue


def test_validate_against_sequence_matches():
    sequence = "MEEPQSD"
    v = Variant.parse("E2A")  # 1-based: position 2 is 'E'
    validate_against_sequence(v, sequence)  # should not raise


def test_validate_against_sequence_mismatch_raises():
    sequence = "MEEPQSD"
    v = Variant.parse("Q2A")  # position 2 is actually 'E', not 'Q'
    with pytest.raises(ValueError, match="Reference mismatch"):
        validate_against_sequence(v, sequence)


def test_score_substitution_is_m_diff():
    M = make_fake_matrix(10)
    result = score_substitution(M, 3, "A", "C")
    expected = M[2, AA_INDEX["C"]] - M[2, AA_INDEX["A"]]
    assert result == pytest.approx(expected)


def test_score_variant_is_additive():
    M = make_fake_matrix(10)
    v = Variant.parse("A3C:D5E")
    single_a = score_substitution(M, 3, "A", "C")
    single_b = score_substitution(M, 5, "D", "E")
    assert score_variant(M, v) == pytest.approx(single_a + single_b)


def test_full_effect_map_zero_at_wildtype():
    L = 10
    wt_sequence = "ACDEFGHIKL"
    M = make_fake_matrix(L)
    effect_map = full_effect_map(M, wt_sequence)
    for i, aa in enumerate(wt_sequence):
        assert effect_map[i, AA_INDEX[aa]] == pytest.approx(0.0)


def test_per_residue_impact_shape_and_excludes_wildtype():
    L = 10
    wt_sequence = "ACDEFGHIKL"
    M = make_fake_matrix(L)
    impact = per_residue_impact(M, wt_sequence, reduce="mean")
    assert impact.shape == (L,)
    assert not np.isnan(impact).any()


def test_substitution_pool_excludes_wildtype_entries():
    """
    The pool must be 19 per position, not 20. Each position's wildtype column
    is exactly 0.0 by construction; leaving those in would put L artificial
    zeros near the top of a mostly-negative distribution and inflate every
    percentile.
    """
    L = 10
    wt_sequence = "ACDEFGHIKL"
    effect_map = full_effect_map(make_fake_matrix(L), wt_sequence)
    pool = substitution_llrs(effect_map, wt_sequence)
    assert pool.size == 19 * L
    for i, aa in enumerate(wt_sequence):
        assert effect_map[i, AA_INDEX[aa]] == pytest.approx(0.0)


def test_llr_percentile_is_higher_for_more_damaging():
    L = 12
    wt_sequence = "ACDEFGHIKLMN"
    effect_map = full_effect_map(make_fake_matrix(L), wt_sequence)
    pool = substitution_llrs(effect_map, wt_sequence)

    worst = llr_percentile(effect_map, wt_sequence, float(pool.min()))
    best = llr_percentile(effect_map, wt_sequence, float(pool.max()))
    middle = llr_percentile(effect_map, wt_sequence, float(np.median(pool)))

    assert worst > middle > best
    assert 0.0 <= best and worst <= 100.0
    assert middle == pytest.approx(50.0, abs=1.0)


def test_llr_percentile_midrank_on_ties():
    """A value tying with part of the pool sits at the middle of its own tie
    block, so identical scores cannot be reported as different extremes."""
    L = 4
    wt_sequence = "ACDE"
    effect_map = np.zeros((L, 20), dtype=np.float32)
    # Every real substitution scores -1.0; wildtype columns stay 0.0.
    mask = np.ones((L, 20), dtype=bool)
    for i, aa in enumerate(wt_sequence):
        mask[i, AA_INDEX[aa]] = False
    effect_map[mask] = -1.0

    # The whole pool ties with the queried value -> exactly mid-rank.
    assert llr_percentile(effect_map, wt_sequence, -1.0) == pytest.approx(50.0)
    # Strictly worse than everything in the pool.
    assert llr_percentile(effect_map, wt_sequence, -9.0) == pytest.approx(100.0)
    # Strictly milder than everything in the pool.
    assert llr_percentile(effect_map, wt_sequence, 0.5) == pytest.approx(0.0)


def test_llr_percentile_hand_computed():
    """Three of nineteen substitutions at this position are milder, so a
    hand-countable case pins the arithmetic rather than trusting numpy."""
    wt_sequence = "A"
    effect_map = np.full((1, 20), -5.0, dtype=np.float32)
    effect_map[0, AA_INDEX["A"]] = 0.0  # wildtype column, excluded
    for aa in ("C", "D", "E"):
        effect_map[0, AA_INDEX[aa]] = -1.0  # milder than the query

    # Pool = 19 values: three at -1.0, sixteen at -5.0. Query -3.0 beats the three.
    assert llr_percentile(effect_map, wt_sequence, -3.0) == pytest.approx(
        100.0 * 3 / 19
    )
