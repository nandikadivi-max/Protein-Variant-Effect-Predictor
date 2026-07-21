"""Unit tests for AnnotationService matching/aggregation logic. No network."""

import pytest

from api.services.annotation_service import AnnotationService
from domain.derive import Variant

R175H_FEATURES = [
    {
        "begin": "175", "end": "175", "wildType": "R", "alternativeSequence": "H",
        "clinicalSignificances": [
            {"type": "Benign", "sources": ["Ensembl"]},
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
    # most-actionable significance wins over the benign call
    assert ann.clinical_significance == "Pathogenic"
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
