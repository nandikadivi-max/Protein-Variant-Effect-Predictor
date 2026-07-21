"""
AnnotationService — turns a mutation into a VariantAnnotation by matching
it against the EBI Proteins variation data for its UniProt entry.

v1 annotates single substitutions only; multi-substitution variants return
None (each catalogued variant is a single residue change). FASTA-only
proteins have no UniProt identity and so no annotation.
"""

from contracts.schemas import VariantAnnotation, VariantPrediction
from domain.derive import Variant

# Prefer the most clinically actionable call when a variant carries several.
_SIGNIFICANCE_RANK = {
    "pathogenic": 5,
    "likely pathogenic": 4,
    "risk factor": 3,
    "uncertain significance": 2,
    "variant of uncertain significance": 2,
    "likely benign": 1,
    "benign": 0,
}


class AnnotationService:
    def __init__(self, client) -> None:
        self.client = client

    async def annotate(
        self, uniprot_id: str, variant: Variant
    ) -> VariantAnnotation | None:
        if len(variant.substitutions) != 1:
            return None
        sub = variant.substitutions[0]

        features = await self.client.fetch_variants(uniprot_id)
        matches = [
            f
            for f in features
            if str(f.get("begin")) == str(sub.position)
            and f.get("wildType") == sub.wt
            and f.get("alternativeSequence") == sub.mut
        ]
        if not matches:
            return None

        sources: set[str] = set()
        diseases: list[str] = []
        seen_disease: set[str] = set()
        predictions: list[VariantPrediction] = []
        significances: list[str] = []

        for f in matches:
            for cs in f.get("clinicalSignificances") or []:
                if cs.get("type"):
                    significances.append(cs["type"])
                sources.update(cs.get("sources") or [])
            for assoc in f.get("association") or []:
                name = assoc.get("name")
                if assoc.get("disease") and name and name not in seen_disease:
                    seen_disease.add(name)
                    diseases.append(name)
            for p in f.get("predictions") or []:
                predictions.append(
                    VariantPrediction(
                        algorithm=p.get("predAlgorithmNameType", "unknown"),
                        prediction=p.get("predictionValType"),
                        score=p.get("score"),
                    )
                )

        return VariantAnnotation(
            mutation=str(variant),
            clinical_significance=self._pick_significance(significances),
            sources=sorted(sources),
            diseases=diseases[:10],
            predictions=predictions,
        )

    @staticmethod
    def _pick_significance(significances: list[str]) -> str | None:
        if not significances:
            return None
        return max(significances, key=lambda s: _SIGNIFICANCE_RANK.get(s.lower(), -1))
