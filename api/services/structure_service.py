"""
StructureService — fetch-once-then-serve orchestration for 3D structures.

Mirrors the "compute once, derive everything" discipline of the scoring
path: a protein's structure file is downloaded from AlphaFold/RCSB exactly
once, persisted to the structure store, and recorded in the `structures`
table keyed by sequence_hash. Every later request (viewer, DSSP) reads the
stored copy.

Provider selection in v1:
  - protein has a uniprot_id  -> AlphaFold predicted model
  - protein is FASTA-only     -> no structure available (returns None)
  - PDB-sourced proteins      -> RCSB (wired in 4b alongside SIFTS mapping)
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.structure_client import StructureClient, StructureNotFound
from db.models import Protein, Structure
from storage.structure_store import StructureStore


@dataclass(frozen=True)
class StructureRecord:
    sequence_hash: str
    provider: str
    fmt: str
    source_url: str
    structure_uri: str


class StructureService:
    def __init__(
        self,
        session: AsyncSession,
        store: StructureStore,
        client: StructureClient,
    ) -> None:
        self.session = session
        self.store = store
        self.client = client

    async def get_or_fetch(self, sequence_hash: str) -> StructureRecord | None:
        """
        Return the stored structure record, fetching + persisting it on first
        request. Returns None when the protein is unknown or has no structure
        source (FASTA-only input).
        """
        existing = await self._load_row(sequence_hash)
        if existing is not None:
            return self._to_record(existing)

        protein = await self._load_protein(sequence_hash)
        if protein is None:
            return None

        # Fetch from the appropriate provider. Only AlphaFold (UniProt) is
        # wired in 4a; RCSB/PDB lands in 4b.
        if protein.uniprot_id:
            try:
                data, source_url = await self.client.fetch_alphafold(protein.uniprot_id)
            except StructureNotFound:
                return None
            provider = "alphafold"
        else:
            return None

        fmt = "pdb"
        uri = self.store.write(sequence_hash, fmt, data)
        await self._upsert_row(sequence_hash, provider, uri, source_url)
        return StructureRecord(
            sequence_hash=sequence_hash,
            provider=provider,
            fmt=fmt,
            source_url=source_url,
            structure_uri=uri,
        )

    async def read_file(self, sequence_hash: str) -> tuple[bytes, str] | None:
        """Return (raw_bytes, format) for a fetched structure, or None."""
        record = await self.get_or_fetch(sequence_hash)
        if record is None:
            return None
        return self.store.read(record.structure_uri), record.fmt

    async def _load_row(self, sequence_hash: str) -> Structure | None:
        result = await self.session.execute(
            select(Structure).where(Structure.sequence_hash == sequence_hash)
        )
        return result.scalar_one_or_none()

    async def _load_protein(self, sequence_hash: str) -> Protein | None:
        result = await self.session.execute(
            select(Protein).where(Protein.sequence_hash == sequence_hash)
        )
        return result.scalar_one_or_none()

    async def _upsert_row(
        self, sequence_hash: str, provider: str, uri: str, source_url: str
    ) -> None:
        stmt = (
            pg_insert(Structure)
            .values(
                sequence_hash=sequence_hash,
                provider=provider,
                structure_uri=uri,
                source_url=source_url,
            )
            .on_conflict_do_nothing(index_elements=["sequence_hash"])
        )
        await self.session.execute(stmt)
        await self.session.commit()

    @staticmethod
    def _to_record(row: Structure) -> StructureRecord:
        fmt = row.structure_uri.rsplit(".", 1)[-1] if "." in row.structure_uri else "pdb"
        return StructureRecord(
            sequence_hash=row.sequence_hash,
            provider=row.provider,
            fmt=fmt,
            source_url=row.source_url or "",
            structure_uri=row.structure_uri,
        )
