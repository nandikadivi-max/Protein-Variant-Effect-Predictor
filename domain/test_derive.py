import numpy as np
import pytest

from domain.derive import (
    Substitution,
    Variant,
    full_effect_map,
    per_residue_impact,
    score_substitution,
    score_variant,
    validate_against_sequence,
)
from domain.scoring import AA_INDEX, AA_ORDER


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
