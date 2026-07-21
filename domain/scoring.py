"""
The Scorer protocol — the single seam every protein language model implements.

FROZEN: AA_ORDER defines the column order of every (L, 20) matrix in this
system. Every scorer implementation MUST gather its output into exactly
this order, regardless of the underlying model's native vocabulary order.
Never change this order after data has been written to score_matrices.
"""

from typing import Protocol

import numpy as np

AA_ORDER: str = "ACDEFGHIKLMNPQRSTVWY"
AA_INDEX: dict[str, int] = {aa: i for i, aa in enumerate(AA_ORDER)}

MAX_SEQUENCE_LENGTH = 1022  # ESM-2 practical context limit


class SequenceTooLongError(ValueError):
    """Raised when a sequence exceeds MAX_SEQUENCE_LENGTH."""


class InvalidResidueError(ValueError):
    """Raised when a sequence contains characters outside AA_ORDER."""


def validate_sequence(sequence: str) -> None:
    """Raise if the sequence is empty, too long, or has non-canonical residues."""
    if not sequence:
        raise ValueError("Sequence is empty")
    if len(sequence) > MAX_SEQUENCE_LENGTH:
        raise SequenceTooLongError(
            f"Sequence length {len(sequence)} exceeds max {MAX_SEQUENCE_LENGTH}. "
            "Windowing is not supported in v1."
        )
    invalid = set(sequence) - set(AA_ORDER)
    if invalid:
        raise InvalidResidueError(f"Non-canonical residues found: {sorted(invalid)}")


class Scorer(Protocol):
    """
    Every protein language model backend implements this single method.
    This is the ONLY place a model forward pass happens in the whole system.

    Adding a new model (SaProt, ESM C, ProtT5, an ensemble) means writing a
    new class that satisfies this protocol. No caller-side code changes.
    """

    model_id: str

    def per_position_log_probs(self, sequence: str) -> np.ndarray:
        """
        Return an (L, 20) float32 array of log-probabilities, where L is
        len(sequence) and columns are ordered per AA_ORDER.

        M[i, j] = log P(residue at position i == AA_ORDER[j] | context)
        """
        ...
