"""Unit tests for AnnotationService matching/aggregation logic. No network."""

import pytest

from api.services.annotation_service import AnnotationService
from domain.derive import Variant

R175H_FEATURES = [
    {
        "begin": "175", "end": "175", "wildType": "R", "alternativeSequence": "H",
        "clinicalSignificances": [
            {"type": "Likely pathogenic", "sources": ["Ensembl"]},
            {"type": "Pathogenic", "sources": ["ClinVar", "UniProt"]},
        ],
        "association": [
            {"name": "Li-Fraumeni syndrome", "disease": True},
            {"name": "Li-Fraumeni syndrome", "disease": True},  # duplicate
            {"name": "Not a disease", "disease": False},
        ],
        "predictions": [
            {"predAlgorithmNameType": "SIFT", "predictionValType": "deleterious", "score": 0.0},
        ],
    },
    {  # same position, different substitution — must not match R175H
        "begin": "175", "end": "175", "wildType": "R", "alternativeSequence": "C",
        "clinicalSignificances": [{"type": "Benign", "sources": ["Ensembl"]}],
    },
]


class _FakeClient:
    def __init__(self, features):
        self.features = features

    async def fetch_variants(self, accession):
        return self.features


@pytest.mark.asyncio
async def test_annotate_matches_single_substitution():
    svc = AnnotationService(_FakeClient(R175H_FEATURES))
    ann = await svc.annotate("P04637", Variant.parse("R175H"))

    assert ann is not None
    assert ann.mutation == "R175H"
    # the two calls agree in direction, so the more actionable one wins
    assert ann.clinical_significance == "Pathogenic"
    assert ann.significances == ["Pathogenic", "Likely pathogenic"]
    assert ann.sources == ["ClinVar", "Ensembl", "UniProt"]
    assert ann.diseases == ["Li-Fraumeni syndrome"]  # deduped, non-disease dropped
    assert len(ann.predictions) == 1
    assert ann.predictions[0].algorithm == "SIFT"


@pytest.mark.asyncio
async def test_multi_substitution_is_not_annotated():
    svc = AnnotationService(_FakeClient(R175H_FEATURES))
    assert await svc.annotate("P04637", Variant.parse("R175H:D281N")) is None


@pytest.mark.asyncio
async def test_no_match_returns_none():
    svc = AnnotationService(_FakeClient(R175H_FEATURES))
    # position present but wrong substitution target
    assert await svc.annotate("P04637", Variant.parse("R175W")) is None


@pytest.mark.asyncio
async def test_empty_variant_list_returns_none():
    svc = AnnotationService(_FakeClient([]))
    assert await svc.annotate("P04637", Variant.parse("R175H")) is None


# The shape EBI really returns for TP53 P72R: two features for one amino-acid
# change, because two different codon changes reach it. rs1042522 is the
# common polymorphism (a quarter of the population carries it) and is Benign;
# a separate somatic entry is Pathogenic. Taking the most severe used to
# report this famously harmless variant as disease-causing.
P72R_FEATURES = [
    {
        "begin": "72", "end": "72", "wildType": "P", "alternativeSequence": "R",
        "clinicalSignificances": [{"type": "Benign", "sources": ["ClinVar"]}],
    },
    {
        "begin": "72", "end": "72", "wildType": "P", "alternativeSequence": "R",
        "clinicalSignificances": [
            {"type": "Pathogenic", "sources": ["Ensembl", "ClinVar"]}
        ],
    },
]


@pytest.mark.asyncio
async def test_disagreeing_calls_are_reported_as_conflicting():
    svc = AnnotationService(_FakeClient(P72R_FEATURES))
    ann = await svc.annotate("P04637", Variant.parse("P72R"))

    assert ann is not None
    assert ann.clinical_significance == "Conflicting interpretations"
    # both calls are kept so the UI can show what the disagreement actually is
    assert ann.significances == ["Pathogenic", "Benign"]
    assert ann.sources == ["ClinVar", "Ensembl"]


@pytest.mark.asyncio
async def test_risk_factor_alongside_benign_is_not_a_conflict():
    """A risk factor is a modifier, not a contradiction of a benign call."""
    features = [
        {
            "begin": "10", "end": "10", "wildType": "A", "alternativeSequence": "V",
            "clinicalSignificances": [
                {"type": "Benign", "sources": ["ClinVar"]},
                {"type": "Risk factor", "sources": ["UniProt"]},
            ],
        }
    ]
    svc = AnnotationService(_FakeClient(features))
    ann = await svc.annotate("P04637", Variant.parse("A10V"))

    assert ann is not None
    assert ann.clinical_significance == "Risk factor"


@pytest.mark.asyncio
async def test_agreeing_benign_calls_stay_benign():
    features = [
        {
            "begin": "10", "end": "10", "wildType": "A", "alternativeSequence": "V",
            "clinicalSignificances": [
                {"type": "Likely benign", "sources": ["Ensembl"]},
                {"type": "Benign", "sources": ["ClinVar"]},
            ],
        }
    ]
    svc = AnnotationService(_FakeClient(features))
    ann = await svc.annotate("P04637", Variant.parse("A10V"))

    assert ann is not None
    assert ann.clinical_significance == "Likely benign"
