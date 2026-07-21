"""
The smoke test. TP53 R175H is one of the most studied cancer hotspot
mutations in existence — it MUST score as damaging. If this test fails,
do not trust anything downstream: the bug is almost always a coordinate
or special-token offset error in the scorer, not the model itself.

This is slow (loads a 650M param model) — run explicitly, not in the
default fast test suite:
    pytest worker/scorers/test_esm2_smoke.py -v -s
"""

import pytest

torch = pytest.importorskip("torch", reason="requires the worker extras: pip install -e '.[worker]'")

from domain.derive import score_substitution
from worker.scorers.esm2 import ESM2Scorer

# TP53 canonical sequence (UniProt P04637), truncated is NOT ok here —
# we need the real full-length sequence for position 175 to be meaningful.
TP53_SEQUENCE = (
    "MEEPQSDPSVEPPLSQETFSDLWKLLPENNVLSPLPSQAMDDLMLSPDDIEQWFTEDPGPDEAPRMPEAAPPVAPAP"
    "AAPTPAAPAPAPSWPLSSSVPSQKTYQGSYGFRLGFLHSGTAKSVTCTYSPALNKMFCQLAKTCPVQLWVDSTPPPG"
    "TRVRAMAIYKQSQHMTEVVRRCPHHERCSDSDGLAPPQHLIRVEGNLRVEYLDDRNTFRHSVVVPYEPPEVGSDCTT"
    "IHYNYMCNSSCMGGMNRRPILTIITLEDSSGNLLGRNSFEVRVCACPGRDRRTEEENLRKKGEPHHELPPGSTKRAL"
    "PNNTSSSPQPKKKPLDGEYFTLQIRGRERFEMFRELNEALELKDAQAGKEPGGSRAHSSHLKSKKGQSTSRHKKLMF"
    "KTEGPDSD"
)


@pytest.fixture(scope="module")
def scorer() -> ESM2Scorer:
    return ESM2Scorer()


def test_tp53_r175h_scores_damaging(scorer: ESM2Scorer) -> None:
    position = 175
    wt, mut = "R", "H"
    assert TP53_SEQUENCE[position - 1] == wt, "Reference sequence/position mismatch"

    M = scorer.per_position_log_probs(TP53_SEQUENCE)
    llr = score_substitution(M, position, wt, mut)

    print(f"\nTP53 R175H LLR = {llr:.4f} (negative = damaging)")
    assert llr < 0, (
        f"Expected R175H to score as damaging (LLR < 0), got {llr:.4f}. "
        "Check AA_ORDER alignment, special-token offsets, and position indexing."
    )


def test_tp53_r175h_more_damaging_than_synonymous_like_change(scorer: ESM2Scorer) -> None:
    """R175H (hotspot, damaging) should score more negatively than a
    conservative substitution at a tolerant, solvent-exposed position."""
    M = scorer.per_position_log_probs(TP53_SEQUENCE)
    hotspot_llr = score_substitution(M, 175, "R", "H")
    # position 1 (Met start, not a real comparison point) swapped for a
    # late, less-constrained-looking position as a rough sanity contrast.
    benign_like_llr = score_substitution(M, 372, "K", "R")  # conservative, same charge class

    print(f"\nHotspot R175H LLR={hotspot_llr:.4f} vs conservative K372R LLR={benign_like_llr:.4f}")
    assert hotspot_llr < benign_like_llr
