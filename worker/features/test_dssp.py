"""
Tests for DSSP structural feature extraction.

Needs the dssp/mkdssp binary (skipped if absent) and network access to
fetch a real structure.

Run explicitly:
    pytest worker/features/test_dssp.py -v -m network
"""

import shutil

import pytest

pytestmark = pytest.mark.network

if not (shutil.which("mkdssp") or shutil.which("dssp")):
    pytest.skip("no dssp/mkdssp binary on PATH", allow_module_level=True)

from api.services.structure_client import StructureClient
from worker.features.dssp import compute_structure_context

# Crambin (PDB 1CRN): 46 residues, author numbering == UniProt numbering.
CRAMBIN_LEN = 46
CRAMBIN_SEGMENTS = [
    {"chain_id": "A", "pdb_start": 1, "pdb_end": 46, "unp_start": 1, "unp_end": 46}
]


@pytest.fixture(scope="module")
async def crambin_pdb() -> bytes:
    client = StructureClient()
    try:
        data, _ = await client.fetch_rcsb("1CRN")
    finally:
        await client.aclose()
    return data


@pytest.mark.asyncio
async def test_crambin_context_shape_and_values(crambin_pdb):
    ctx = compute_structure_context(crambin_pdb, CRAMBIN_LEN, CRAMBIN_SEGMENTS)

    assert len(ctx.secondary_structure) == CRAMBIN_LEN
    assert len(ctx.relative_sasa) == CRAMBIN_LEN
    assert len(ctx.buried) == CRAMBIN_LEN

    assert set(ctx.secondary_structure) <= {"H", "E", "C"}
    assert all(0.0 <= r <= 1.0 for r in ctx.relative_sasa)
    # crambin has both an alpha helix and a beta sheet.
    assert "H" in ctx.secondary_structure
    assert "E" in ctx.secondary_structure
    # buried must be consistent with the RSA threshold.
    assert all(b == (r < 0.20) for b, r in zip(ctx.buried, ctx.relative_sasa))


@pytest.mark.asyncio
async def test_identity_mapping_matches_sifts_for_crambin(crambin_pdb):
    """For crambin, SIFTS numbering == author numbering, so passing segments
    or None (identity) must give the same result."""
    with_segments = compute_structure_context(crambin_pdb, CRAMBIN_LEN, CRAMBIN_SEGMENTS)
    identity = compute_structure_context(crambin_pdb, CRAMBIN_LEN, None)
    assert with_segments.secondary_structure == identity.secondary_structure
    assert with_segments.relative_sasa == identity.relative_sasa
