"""
Integration test: a PDB (experimental) structure takes precedence over an
already-recorded AlphaFold (predicted) one. DB only, no network.

Run with:
    pytest tests/test_structure_precedence.py -v -m integration
"""

import pytest

pytestmark = pytest.mark.integration

asyncpg = pytest.importorskip("asyncpg", reason="requires api/dev extras")

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from api.services.sifts_client import SiftsMapping, SiftsSegment
from api.services.structure_service import StructureService
from db.models import Protein, Structure
from db.session import async_session_factory
from storage.structure_store import get_structure_store

HASH = "precedence" + "0" * 54  # 64 chars
MAPPING = SiftsMapping(
    pdb_id="1abc",
    uniprot_accession="P12345",
    uniprot_name="TEST",
    segments=(SiftsSegment(chain_id="A", pdb_start=1, pdb_end=10, unp_start=1, unp_end=10),),
)


@pytest.mark.asyncio
async def test_pdb_intent_overrides_alphafold_row():
    async with async_session_factory() as session:
        store = get_structure_store()
        svc = StructureService(session, store)

        # Clean slate.
        await session.execute(delete(Structure).where(Structure.sequence_hash == HASH))
        await session.execute(delete(Protein).where(Protein.sequence_hash == HASH))
        # Protein + a pre-existing fetched AlphaFold structure.
        await session.execute(
            pg_insert(Protein).values(
                sequence_hash=HASH, sequence="MKV", length=3,
                uniprot_id="P12345", source="test",
            )
        )
        af_uri = store.write(HASH, "pdb", b"ALPHAFOLD")
        await session.execute(
            pg_insert(Structure).values(
                sequence_hash=HASH, provider="alphafold",
                structure_uri=af_uri, source_url="af",
            )
        )
        await session.commit()

        # Resolving a PDB records the experimental intent — must override.
        await svc.record_pdb_intent(HASH, MAPPING)
        row = (
            await session.execute(select(Structure).where(Structure.sequence_hash == HASH))
        ).scalar_one()
        assert row.provider == "rcsb"
        assert row.pdb_id == "1abc"
        assert row.structure_uri is None  # reset so RCSB is fetched fresh
        assert row.sifts_map_uri is not None

        # Idempotent: recording again keeps the rcsb row unchanged.
        await svc.record_pdb_intent(HASH, MAPPING)
        row2 = (
            await session.execute(select(Structure).where(Structure.sequence_hash == HASH))
        ).scalar_one()
        assert row2.provider == "rcsb"

        # Cleanup.
        await session.execute(delete(Structure).where(Structure.sequence_hash == HASH))
        await session.execute(delete(Protein).where(Protein.sequence_hash == HASH))
        await session.commit()
