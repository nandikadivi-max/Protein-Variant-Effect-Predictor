"""
Turning a rejected input into a specific, actionable correction.

Every failure this module explains is one we can diagnose exactly, because
by the time validation fails we already hold the real sequence. That matters:
we can *know* the user meant E7V rather than guess at it, and a suggestion
that is merely plausible is worse than none — it looks just as confident as
a correct one.

Pure functions only. No network, no database, no model.
"""

from dataclasses import dataclass

from domain.derive import Substitution, Variant

# Full names, so a message can say "proline (P)" rather than a bare letter to
# someone who doesn't have the single-letter code memorised.
AA_NAMES: dict[str, str] = {
    "A": "alanine", "C": "cysteine", "D": "aspartic acid", "E": "glutamic acid",
    "F": "phenylalanine", "G": "glycine", "H": "histidine", "I": "isoleucine",
    "K": "lysine", "L": "leucine", "M": "methionine", "N": "asparagine",
    "P": "proline", "Q": "glutamine", "R": "arginine", "S": "serine",
    "T": "threonine", "V": "valine", "W": "tryptophan", "Y": "tyrosine",
}

# How far to look either side for the residue the user expected. Kept small on
# purpose: a match six positions away is more likely coincidence than intent,
# and a confidently wrong suggestion is the failure mode to avoid.
_SEARCH_RADIUS = 3

# +1 first. Clinical variant names usually number the mature protein, after
# the initiator methionine is cleaved, so the canonical position is typically
# one HIGHER than the familiar name (sickle-cell E6V is E7V in UniProt).
_OFFSETS = (1, -1, 2, -2, 3, -3)


@dataclass(frozen=True)
class Suggestion:
    """A concrete replacement the user can apply in one click."""

    mutation: str
    reason: str


def describe_residue(letter: str) -> str:
    name = AA_NAMES.get(letter.upper())
    return f"{name} ({letter.upper()})" if name else letter.upper()


def explain_and_suggest(
    variant: Variant, sequence: str
) -> tuple[str, list[Suggestion]]:
    """
    Explain why `variant` doesn't fit `sequence`, and propose fixes.

    Returns (explanation, suggestions). The explanation is always populated;
    suggestions may be empty when nothing defensible can be offered.
    Assumes the variant has already failed validation.
    """
    length = len(sequence)

    for sub in variant.substitutions:
        if sub.position > length:
            return (
                f"This protein has {length} residues, so there is no position "
                f"{sub.position}.",
                [],
            )
        actual = sequence[sub.position - 1]
        if actual == sub.wt:
            continue  # this one is fine; keep looking

        explanation = (
            f"Position {sub.position} is {describe_residue(actual)}, not "
            f"{describe_residue(sub.wt)}."
        )
        return explanation, _fixes_for(sub, sequence, actual)

    return "This mutation doesn't match the sequence.", []


def _fixes_for(
    sub: Substitution, sequence: str, actual: str
) -> list[Suggestion]:
    """Candidate corrections for one mismatched substitution."""
    suggestions: list[Suggestion] = []
    length = len(sequence)

    # 1. The user's residue exists nearby — almost always a numbering offset.
    for delta in _OFFSETS:
        pos = sub.position + delta
        if not (1 <= pos <= length) or abs(delta) > _SEARCH_RADIUS:
            continue
        if sequence[pos - 1] != sub.wt:
            continue
        reason = (
            "Clinical variant names often number the mature protein, after the "
            "starting methionine is removed. This tool uses UniProt numbering, "
            "which counts it."
            if delta == 1
            else f"{describe_residue(sub.wt)} is at position {pos} in this sequence."
        )
        suggestions.append(
            Suggestion(mutation=f"{sub.wt}{pos}{sub.mut}", reason=reason)
        )
        break  # one offset candidate is enough; more reads as guessing

    # 2. Keep the position, correct the residue that's actually there.
    if actual != sub.mut:
        suggestions.append(
            Suggestion(
                mutation=f"{actual}{sub.position}{sub.mut}",
                reason=f"Keep position {sub.position}, which holds "
                f"{describe_residue(actual)}.",
            )
        )

    return suggestions


def explain_parse_failure(raw: str) -> str:
    """A readable version of 'that isn't a mutation'."""
    cleaned = raw.strip()
    if not cleaned:
        return "Enter a mutation like R175H, or leave it blank for the full map."
    return (
        f"'{cleaned[:32]}' isn't a mutation. Use the original residue, the "
        "position, then the new residue, like R175H. Combine several with a "
        "colon: R175H:D281N."
    )
