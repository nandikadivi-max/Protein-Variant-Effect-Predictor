"""
Results service — reads a cached matrix and computes all the derived
products (single-mutation score, effect map, per-residue impact) for
the API response.

This is where the "compute once, derive everything" design pays off:
every call to build_result() is fast (pure array ops on an already-
loaded matrix), no matter how many mutations or how large the heatmap.
"""

from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.annotation_service import AnnotationService
from api.services.structure_service import StructureService
from contracts.schemas import EffectLabel, ScoreResult, SingleScore
from db.models import Protein, ScoreMatrix
from domain.derive import (
    Variant,
    full_effect_map,
    per_residue_impact,
    score_variant,
    validate_against_sequence,
)
from storage.matrix_store import MatrixStore

# Initial thresholds. These become data-driven once the ProteinGym
# calibration harness runs in Phase 7 — until then, use these placeholder
# bounds so the API response schema is complete.
DAMAGING_LLR_THRESHOLD = -3.0
TOLERATED_LLR_THRESHOLD = -0.5


def classify_llr(llr: float) -> EffectLabel:
    if llr < DAMAGING_LLR_THRESHOLD:
        return EffectLabel.LIKELY_DAMAGING
    if llr > TOLERATED_LLR_THRESHOLD:
        return EffectLabel.LIKELY_TOLERATED
    return EffectLabel.UNCERTAIN


@dataclass(frozen=True)
class _LoadedMatrix:
    matrix: np.ndarray
    sequence: str
    model_id: str
    uniprot_id: str | None


class ResultsService:
    def __init__(
        self,
        session: AsyncSession,
        matrix_store: MatrixStore,
        structures: StructureService | None = None,
        annotations: AnnotationService | None = None,
    ) -> None:
        self.session = session
        self.matrix_store = matrix_store
        # Optional: when present, the response carries DSSP structural context
        # (secondary structure / RSA / buried) if the worker has computed it.
        self.structures = structures
        # Optional: external variant annotations (ClinVar/Ensembl clinical
        # significance + SIFT/PolyPhen) for the single mutation, when known.
        self.annotations = annotations

    async def _load(self, sequence_hash: str, model_id: str) -> _LoadedMatrix | None:
        result = await self.session.execute(
            select(ScoreMatrix, Protein)
            .join(Protein, ScoreMatrix.sequence_hash == Protein.sequence_hash)
            .where(
                ScoreMatrix.sequence_hash == sequence_hash,
                ScoreMatrix.model_id == model_id,
            )
        )
        row = result.first()
        if row is None:
            return None
        score_matrix_row, protein_row = row
        matrix = self.matrix_store.read(score_matrix_row.matrix_uri)
        return _LoadedMatrix(
            matrix=matrix,
            sequence=protein_row.sequence,
            model_id=model_id,
            uniprot_id=protein_row.uniprot_id,
        )

    async def build_result(
        self, sequence_hash: str, model_id: str, mutation: str | None = None
    ) -> ScoreResult | None:
        loaded = await self._load(sequence_hash, model_id)
        if loaded is None:
            return None

        single: SingleScore | None = None
        annotation = None
        if mutation:
            variant = Variant.parse(mutation)
            validate_against_sequence(variant, loaded.sequence)
            llr = score_variant(loaded.matrix, variant)
            single = SingleScore(mutation=str(variant), llr=llr, label=classify_llr(llr))

            # External variant annotation (best-effort). Never fail the result
            # over an annotation lookup, and skip it for FASTA-only proteins.
            if self.annotations and loaded.uniprot_id:
                try:
                    annotation = await self.annotations.annotate(
                        loaded.uniprot_id, variant
                    )
                except Exception:  # noqa: BLE001
                    annotation = None

        effect_map = full_effect_map(loaded.matrix, loaded.sequence)
        impact = per_residue_impact(loaded.matrix, loaded.sequence, reduce="mean")

        structure = (
            self.structures.load_features(sequence_hash) if self.structures else None
        )

        return ScoreResult(
            sequence_hash=sequence_hash,
            model_id=model_id,
            length=len(loaded.sequence),
            single=single,
            effect_map=effect_map.tolist(),
            per_residue_impact=impact.tolist(),
            structure=structure,
            annotation=annotation,
        )
