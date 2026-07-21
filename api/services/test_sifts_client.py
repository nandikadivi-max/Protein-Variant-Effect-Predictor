"""
Integration tests for the SIFTS client. These hit the real PDBe API.

Run explicitly:
    pytest api/services/test_sifts_client.py -v -m network
"""

import pytest

from api.services.sifts_client import SiftsClient, SiftsNotFound

pytestmark = pytest.mark.network


@pytest.mark.asyncio
async def test_map_crambin_to_uniprot():
    client = SiftsClient()
    try:
        mapping = await client.map_to_uniprot("1CRN")
    finally:
        await client.aclose()

    assert mapping.pdb_id == "1crn"
    assert mapping.uniprot_accession == "P01542"  # crambin
    assert len(mapping.segments) >= 1
    seg = mapping.segments[0]
    assert seg.chain_id == "A"
    # crambin is a single 46-residue chain, PDB numbering == UniProt numbering
    assert seg.unp_start == 1 and seg.unp_end == 46


@pytest.mark.asyncio
async def test_map_tp53_structure_picks_dominant_chain():
    """A TP53 crystal structure (2OCJ) should map to P04637."""
    client = SiftsClient()
    try:
        mapping = await client.map_to_uniprot("2OCJ")
    finally:
        await client.aclose()
    assert mapping.uniprot_accession == "P04637"
    # DNA-binding domain crystal — UniProt range sits mid-sequence, proving
    # PDB author numbering is mapped to canonical UniProt numbering.
    assert mapping.segments[0].unp_start > 90


@pytest.mark.asyncio
async def test_unknown_pdb_raises():
    client = SiftsClient()
    try:
        with pytest.raises(SiftsNotFound):
            await client.map_to_uniprot("0ZZZ")
    finally:
        await client.aclose()
