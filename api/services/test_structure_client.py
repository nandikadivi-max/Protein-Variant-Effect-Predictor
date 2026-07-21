"""
Integration tests for the structure client. These hit the real AlphaFold
DB and RCSB.

Run explicitly:
    pytest api/services/test_structure_client.py -v -m network
"""

import pytest

from api.services.structure_client import StructureClient, StructureNotFound

pytestmark = pytest.mark.network


@pytest.mark.asyncio
async def test_fetch_alphafold_insulin():
    client = StructureClient()
    try:
        data, source_url = await client.fetch_alphafold("P01308")
    finally:
        await client.aclose()

    text = data.decode("ascii", errors="replace")
    assert "ATOM" in text  # real coordinate records
    assert "AF-P01308-F1" in source_url
    assert len(data) > 1000


@pytest.mark.asyncio
async def test_fetch_alphafold_missing_raises():
    client = StructureClient()
    try:
        with pytest.raises(StructureNotFound):
            await client.fetch_alphafold("ZZZZZZ")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_fetch_rcsb_by_pdb_id():
    client = StructureClient()
    try:
        data, source_url = await client.fetch_rcsb("1CRN")  # crambin, tiny
    finally:
        await client.aclose()

    text = data.decode("ascii", errors="replace")
    assert "ATOM" in text
    assert source_url.endswith("1crn.pdb")
