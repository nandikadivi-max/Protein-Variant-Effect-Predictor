"""
Integration test for the annotation client + service against the real EBI
Proteins variation API.

Run explicitly:
    pytest api/services/test_annotation_client.py -v -m network
"""

import pytest

from api.services.annotation_client import AnnotationClient
from api.services.annotation_service import AnnotationService
from domain.derive import Variant

pytestmark = pytest.mark.network


@pytest.mark.asyncio
async def test_tp53_r175h_is_pathogenic():
    client = AnnotationClient()
    try:
        ann = await AnnotationService(client).annotate("P04637", Variant.parse("R175H"))
    finally:
        await client.aclose()

    assert ann is not None
    assert ann.clinical_significance == "Pathogenic"
    assert "ClinVar" in ann.sources


@pytest.mark.asyncio
async def test_unknown_accession_yields_no_annotation():
    client = AnnotationClient()
    try:
        ann = await AnnotationService(client).annotate("ZZZZZZ", Variant.parse("R175H"))
    finally:
        await client.aclose()
    assert ann is None
