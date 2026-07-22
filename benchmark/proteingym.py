"""
ProteinGym benchmarking core.

Given an assay's wild-type sequence and its deep-mutational-scanning table
(mutant, DMS_score, DMS_score_bin), we score every mutant with our ESM-2
matrix and measure how well the zero-shot LLR tracks experimental fitness
(Spearman). Higher DMS_score = fitter = more tolerated, and a less-negative
LLR also means more tolerated, so a well-behaved model gives a POSITIVE
correlation.

Pure and torch-free: the scorer is injected (any `domain.scoring.Scorer`),
so this module is unit-testable with a fake scorer.
"""

from dataclasses import dataclass, field

import numpy as np

from domain.derive import Variant, score_variant
from domain.scoring import Scorer


@dataclass
class MutantScore:
    mutant: str
    llr: float
    dms_score: float
    dms_bin: int | None


@dataclass
class AssayResult:
    dms_id: str
    n_mutants: int
    n_scored: int
    spearman: float
    scored: list[MutantScore] = field(default_factory=list)


def _rankdata(a: np.ndarray) -> np.ndarray:
    """Average-rank of the data (ties share the mean of their ranks)."""
    a = np.asarray(a, dtype=float)
    order = a.argsort(kind="mergesort")
    ranks = np.empty(len(a), dtype=float)
    ranks[order] = np.arange(1, len(a) + 1)
    sorted_a = a[order]
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        if j > i:
            ranks[order[i : j + 1]] = (i + 1 + j + 1) / 2.0
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float:
    """Spearman rank correlation. Returns nan for <2 points or zero variance."""
    if len(x) < 2:
        return float("nan")
    rx, ry = _rankdata(np.asarray(x)), _rankdata(np.asarray(y))
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def score_assay(
    scorer: Scorer,
    dms_id: str,
    target_seq: str,
    rows: list[dict],
) -> AssayResult:
    """
    Score every mutant in `rows` (each: {mutant, DMS_score, DMS_score_bin})
    against `target_seq`. Mutants whose wild-type residue doesn't match the
    sequence, or that fall outside it, are skipped (assay/sequence drift).
    """
    matrix = scorer.per_position_log_probs(target_seq)
    scored: list[MutantScore] = []

    for row in rows:
        mutant = row["mutant"].strip()
        try:
            variant = Variant.parse(mutant)
        except ValueError:
            continue
        if not _matches(variant, target_seq):
            continue
        llr = score_variant(matrix, variant)
        bin_raw = row.get("DMS_score_bin")
        scored.append(
            MutantScore(
                mutant=mutant,
                llr=llr,
                dms_score=float(row["DMS_score"]),
                dms_bin=int(bin_raw) if bin_raw not in (None, "") else None,
            )
        )

    rho = spearman([m.llr for m in scored], [m.dms_score for m in scored])
    return AssayResult(
        dms_id=dms_id,
        n_mutants=len(rows),
        n_scored=len(scored),
        spearman=rho,
        scored=scored,
    )


def _matches(variant: Variant, sequence: str) -> bool:
    for s in variant.substitutions:
        if s.position < 1 or s.position > len(sequence):
            return False
        if sequence[s.position - 1] != s.wt:
            return False
    return True
