"""
Integration test for PDB-ID resolution (Phase 4b). Assumes:

    docker compose up -d postgres redis

Runs the full PDB path in-process: classify -> SIFTS map -> UniProt
sequence -> persist protein + structure intent. Hits the real PDBe SIFTS
and UniProt APIs.

Run with:
    pytest tests/test_pdb_resolution.py -v -m "integration and network"
"""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.network]

asyncpg = pytest.importorskip("asyncpg", reason="requires api/dev extras")

from sqlalchemy import select

from api.services.protein_resolver import ProteinResolver
from api.services.sifts_client import SiftsClient
from api.services.structure_client import StructureClient
from api.services.structure_service import StructureService
from api.services.uniprot_client import UniProtClient
from db.models import Structure
from db.session import async_session_factory
from storage.structure_store import get_structure_store


@pytest.mark.asyncio
async def test_resolve_crambin_pdb_id():
    async with async_session_factory() as session:
        uniprot = UniProtClient()
        sifts = SiftsClient()
        structure_client = StructureClient()
        structures = StructureService(
            session=session, store=get_structure_store(), client=structure_client
        )
        try:
            resolver = ProteinResolver(
                session=session,
                uniprot=uniprot,
                sifts=sifts,
                structures=structures,
            )
            protein = await resolver.resolve("1CRN")
        finally:
            await uniprot.aclose()
            await sifts.aclose()
            await structure_client.aclose()

        # PDB resolved to its UniProt entry, scored in UniProt coordinates.
        assert protein.uniprot_id == "P01542"
        assert protein.coordinate_system == "uniprot"
        assert len(protein.sequence) == 46
        assert "pdb:1crn" in protein.source

        # A structure intent row was recorded: experimental RCSB provider,
        # the PDB id to fetch, and the persisted SIFTS map.
        row = (
            await session.execute(
                select(Structure).where(
                    Structure.sequence_hash == protein.sequence_hash
                )
            )
        ).scalar_one()
        assert row.provider == "rcsb"
        assert row.pdb_id == "1crn"
        assert row.sifts_map_uri is not None
