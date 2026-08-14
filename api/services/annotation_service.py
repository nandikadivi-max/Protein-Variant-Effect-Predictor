"""
AnnotationService — turns a mutation into a VariantAnnotation by matching
it against the EBI Proteins variation data for its UniProt entry.

v1 annotates single substitutions only; multi-substitution variants return
None (each catalogued variant is a single residue change). FASTA-only
proteins have no UniProt identity and so no annotation.
"""

from api.services.alphamissense_provider import AlphaMissenseProvider
from contracts.schemas import VariantAnnotation, VariantPrediction
from domain.derive import Variant

# Ranked so the most clinically actionable call wins when several agree in
# direction. When they disagree, see _pick_significance — severity alone is
# the wrong tiebreak.
_SIGNIFICANCE_RANK = {
    "pathogenic": 5,
    "likely pathogenic": 4,
    "risk factor": 3,
    "uncertain significance": 2,
    "variant of uncertain significance": 2,
    "likely benign": 1,
    "benign": 0,
}

CONFLICTING = "Conflicting interpretations"


def _direction(significance: str) -> int:
    """
    Which way a call points: +1 disease-causing, -1 benign, 0 neither.

    "Risk factor" and the uncertain calls sit at 0 deliberately. A risk factor
    reported alongside a benign call is not a contradiction; Pathogenic
    alongside Benign is.
    """
    rank = _SIGNIFICANCE_RANK.get(significance.lower())
    if rank is None:
        return 0
    if rank >= 4:
        return 1
    if rank <= 1:
        return -1
    return 0


class AnnotationService:
    def __init__(
        self, client, alphamissense: AlphaMissenseProvider | None = None
    ) -> None:
        self.client = client
        self.alphamissense = alphamissense

    async def annotate(
        self, uniprot_id: str, variant: Variant
    ) -> VariantAnnotation | None:
        if len(variant.substitutions) != 1:
            return None
        sub = variant.substitutions[0]
        mutation = str(variant)

        predictions: list[VariantPrediction] = []

        # AlphaMissense (local dataset, optional). Covers every possible
        # substitution, so it may have a call even when the clinical
        # databases below don't.
        if self.alphamissense is not None:
            am = self.alphamissense.lookup(uniprot_id, mutation)
            if am is not None:
                predictions.append(
                    VariantPrediction(
                        algorithm="AlphaMissense",
                        prediction=am.classification,
                        score=am.score,
                    )
                )

        features = await self.client.fetch_variants(uniprot_id)
        matches = [
            f
            for f in features
            if str(f.get("begin")) == str(sub.position)
            and f.get("wildType") == sub.wt
            and f.get("alternativeSequence") == sub.mut
        ]
        if not matches and not predictions:
            return None

        sources: set[str] = set()
        diseases: list[str] = []
        seen_disease: set[str] = set()
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
            mutation=mutation,
            clinical_significance=self._pick_significance(significances),
            significances=self._distinct(significances),
            sources=sorted(sources),
            diseases=diseases[:10],
            predictions=predictions,
        )

    @staticmethod
    def _distinct(significances: list[str]) -> list[str]:
        """Distinct calls in EBI's own wording, most severe first."""
        unique = list(dict.fromkeys(significances))
        return sorted(unique, key=lambda s: -_SIGNIFICANCE_RANK.get(s.lower(), -1))

    @staticmethod
    def _pick_significance(significances: list[str]) -> str | None:
        """
        Collapse several database calls into one headline.

        Taking the most severe is right when the calls agree in direction and
        wrong when they don't. EBI returns one feature per *genomic* variant,
        so an amino-acid substitution reachable by more than one codon change
        carries more than one entry. TP53 P72R has two: the common rs1042522
        polymorphism, which ClinVar calls Benign, and a separate somatic entry
        called Pathogenic. Reporting only the latter would label a variant
        carried by a quarter of the population as disease-causing. ClinVar
        surfaces the disagreement rather than resolving it, and so do we.
        """
        if not significances:
            return None
        directions = {_direction(s) for s in significances}
        if 1 in directions and -1 in directions:
            return CONFLICTING
        return max(significances, key=lambda s: _SIGNIFICANCE_RANK.get(s.lower(), -1))
