"""
Pure functions deriving all user-facing products from a single (L, 20)
score matrix M. No model knowledge lives here — this module never imports
torch and never runs a forward pass. Everything downstream of a Scorer
call goes through these functions.
"""

from dataclasses import dataclass

import numpy as np

from domain.scoring import AA_INDEX, AA_ORDER


@dataclass(frozen=True)
class Substitution:
    position: int  # 1-based UniProt numbering, as written by users
    wt: str
    mut: str

    def __post_init__(self) -> None:
        if self.wt not in AA_ORDER or self.mut not in AA_ORDER:
            raise ValueError(f"Invalid amino acid in substitution: {self.wt}{self.position}{self.mut}")
        if self.position < 1:
            raise ValueError(f"Position must be >= 1, got {self.position}")


@dataclass(frozen=True)
class Variant:
    substitutions: tuple[Substitution, ...]

    @classmethod
    def parse(cls, mutation_string: str) -> "Variant":
        """Parse 'R248Q' or multi-substitution 'R248Q:D281N' (colon-separated)."""
        subs = []
        for part in mutation_string.strip().split(":"):
            part = part.strip()
            if len(part) < 3:
                raise ValueError(f"Malformed substitution: '{part}'")
            wt, mut = part[0].upper(), part[-1].upper()
            try:
                position = int(part[1:-1])
            except ValueError as e:
                raise ValueError(f"Malformed position in '{part}'") from e
            subs.append(Substitution(position=position, wt=wt, mut=mut))
        return cls(substitutions=tuple(subs))

    def __str__(self) -> str:
        return ":".join(f"{s.wt}{s.position}{s.mut}" for s in self.substitutions)


def validate_against_sequence(variant: Variant, sequence: str) -> None:
    """
    Confirm every substitution's wildtype residue actually matches the
    sequence at that (1-based) position. Raises with the actual residue
    found so the caller can surface a precise error to the user.
    """
    length = len(sequence)
    for s in variant.substitutions:
        if s.position > length:
            raise ValueError(f"Position {s.position} exceeds sequence length {length}")
        actual = sequence[s.position - 1]  # 1-based -> 0-based, the ONE conversion point
        if actual != s.wt:
            raise ValueError(
                f"Reference mismatch at position {s.position}: "
                f"expected '{s.wt}' but sequence has '{actual}'"
            )


def score_substitution(M: np.ndarray, position_1based: int, wt: str, mut: str) -> float:
    """Log-likelihood ratio for a single substitution: M[pos, mut] - M[pos, wt]."""
    pos0 = position_1based - 1
    return float(M[pos0, AA_INDEX[mut]] - M[pos0, AA_INDEX[wt]])


def score_variant(M: np.ndarray, variant: Variant) -> float:
    """Additive masked-marginal approximation across all substitutions."""
    return sum(
        score_substitution(M, s.position, s.wt, s.mut) for s in variant.substitutions
    )


def full_effect_map(M: np.ndarray, wt_sequence: str) -> np.ndarray:
    """
    (L, 20) LLR matrix vs wildtype at every position: effect_map[i, j] =
    M[i, j] - M[i, wt_aa_at_i]. This is the data behind the heatmap.
    """
    L = len(wt_sequence)
    wt_indices = np.array([AA_INDEX[aa] for aa in wt_sequence])
    wt_log_probs = M[np.arange(L), wt_indices][:, None]  # (L, 1)
    return M - wt_log_probs  # broadcast -> (L, 20)


def per_residue_impact(M: np.ndarray, wt_sequence: str, reduce: str = "mean") -> np.ndarray:
    """
    (L,) array summarizing mutational tolerance per position, for 3D
    coloring. 'mean' = average LLR across all 19 non-wildtype substitutions
    (more negative => less tolerant position). 'min' = worst-case LLR.
    """
    effect_map = full_effect_map(M, wt_sequence)
    L = len(wt_sequence)
    wt_indices = np.array([AA_INDEX[aa] for aa in wt_sequence])
    mask = np.ones((L, 20), dtype=bool)
    mask[np.arange(L), wt_indices] = False  # exclude the wildtype-vs-itself zero entry

    masked = np.where(mask, effect_map, np.nan)
    if reduce == "mean":
        return np.nanmean(masked, axis=1)
    if reduce == "min":
        return np.nanmin(masked, axis=1)
    raise ValueError(f"Unknown reduce mode: {reduce}")
