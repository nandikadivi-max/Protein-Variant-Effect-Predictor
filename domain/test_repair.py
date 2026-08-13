"""Tests for input repair suggestions."""

from domain.repair import (
    Suggestion,
    describe_residue,
    explain_and_suggest,
    explain_parse_failure,
)
from domain.derive import Variant

# Real UniProt P68871 (HBB) prefix. Position 1 is the initiator methionine,
# so the clinically famous "E6V" is E7V here.
HBB = "MVHLTPEEKSAVTALWGKVNVDEVGGEALGRLLVVYPWTQRFFESFGDLSTPDAVMGNPKV"

# Real UniProt P00441 (SOD1) prefix. Clinical "A4V" is A5V here.
SOD1 = "MATKAVCVLKGDGPVQGIINFEQKESNGPVKVWGSIKGLTEGLHGFHVHEFGDNTAGCTSA"


def test_mature_protein_offset_is_the_first_suggestion():
    """
    The single most likely user error: typing the clinical variant name.
    Position 6 of HBB is proline; the glutamate is at 7.
    """
    explanation, suggestions = explain_and_suggest(Variant.parse("E6V"), HBB)

    assert "proline" in explanation and "glutamic acid" in explanation
    assert suggestions
    assert suggestions[0].mutation == "E7V"
    assert "mature protein" in suggestions[0].reason


def test_sod1_clinical_name_is_also_repaired():
    explanation, suggestions = explain_and_suggest(Variant.parse("A4V"), SOD1)
    assert "lysine" in explanation  # position 4 is K
    assert suggestions[0].mutation == "A5V"


def test_also_offers_keeping_the_position():
    """Someone who meant that position, but misremembered the residue."""
    _, suggestions = explain_and_suggest(Variant.parse("E6V"), HBB)
    assert Suggestion("P6V", suggestions[-1].reason) == suggestions[-1]
    assert suggestions[-1].mutation == "P6V"
    assert "position 6" in suggestions[-1].reason


def test_position_past_the_end_explains_the_length():
    explanation, suggestions = explain_and_suggest(
        Variant.parse("E999V"), HBB
    )
    assert f"{len(HBB)} residues" in explanation
    assert "no position 999" in explanation
    assert suggestions == []


def test_no_nearby_match_still_offers_the_actual_residue():
    """Nothing within the radius, so only the same-position fix is offered."""
    # Position 3 is H; W appears nowhere near it.
    _, suggestions = explain_and_suggest(Variant.parse("W3A"), HBB)
    assert [s.mutation for s in suggestions] == ["H3A"]


def test_offers_nothing_absurd_when_the_target_equals_the_actual_residue():
    """P6P would be a no-op, so the same-position fix is withheld."""
    _, suggestions = explain_and_suggest(Variant.parse("E6P"), HBB)
    assert all(s.mutation != "P6P" for s in suggestions)


def test_multi_substitution_reports_the_failing_one():
    """The first substitution is valid; the second is not."""
    explanation, suggestions = explain_and_suggest(
        Variant.parse("M1V:E6V"), HBB
    )
    assert "Position 6" in explanation
    assert suggestions[0].mutation == "E7V"


def test_describe_residue_is_readable():
    assert describe_residue("P") == "proline (P)"
    assert describe_residue("e") == "glutamic acid (E)"


def test_parse_failure_messages_are_actionable():
    assert "R175H" in explain_parse_failure("!!!")
    assert "leave it blank" in explain_parse_failure("   ")
    # Long junk is truncated rather than echoed wholesale.
    assert len(explain_parse_failure("X" * 500)) < 200
