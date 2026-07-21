"""
StructureService — fetch-once-then-serve orchestration for 3D structures.

Mirrors the "compute once, derive everything" discipline of the scoring
path: a protein's structure file is downloaded from AlphaFold/RCSB exactly
once, persisted to the structure store, and recorded in the `structures`
table keyed by sequence_hash. Every later request (viewer, DSSP) reads the
stored copy.

Provider selection in v1:
  - PDB-sourced protein       -> RCSB experimental structure. Recorded at
                                 resolve time via record_pdb_intent(); the
                                 file is fetched from RCSB lazily on first
                                 view. This takes precedence — if a
                                 structures row already exists, we honour it.
  - protein has a uniprot_id  -> AlphaFold predicted model (lazy)
  - protein is FASTA-only     -> no structure available (returns None)
"""

import json
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.sifts_client import SiftsMapping
from api.services.structure_client import StructureClient, StructureNotFound
from contracts.schemas import StructureContext
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
        client: StructureClient | None = None,
    ) -> None:
        self.session = session
        self.store = store
        # Only the fetch paths (get_or_fetch, RCSB lazy fetch) need the network
        # client. Reading stored features/sifts works with just the store, so
        # the API's results path can construct this without a client.
        self.client = client

    def _require_client(self) -> StructureClient:
        if self.client is None:
            raise RuntimeError("This StructureService has no network client")
        return self.client

    async def get_or_fetch(self, sequence_hash: str) -> StructureRecord | None:
        """
        Return the stored structure record, fetching + persisting it on first
        request. Returns None when the protein is unknown or has no structure
        source (FASTA-only input).
        """
        existing = await self._load_row(sequence_hash)
        if existing is not None:
            if existing.structure_uri:
                return self._to_record(existing)
            # A recorded-but-not-yet-fetched PDB intent: download it now.
            if existing.provider == "rcsb" and existing.pdb_id:
                return await self._fetch_rcsb_into(existing)
            return None

        protein = await self._load_protein(sequence_hash)
        if protein is None:
            return None

        # No structures row and no PDB intent: fall back to AlphaFold if the
        # protein carries a UniProt identity, else there's nothing to show.
        if not protein.uniprot_id:
            return None
        try:
            data, source_url = await self._require_client().fetch_alphafold(
                protein.uniprot_id
            )
        except StructureNotFound:
            return None

        uri = self.store.write(sequence_hash, "pdb", data)
        await self._upsert_row(sequence_hash, "alphafold", uri, source_url)
        return StructureRecord(
            sequence_hash=sequence_hash,
            provider="alphafold",
            fmt="pdb",
            source_url=source_url,
            structure_uri=uri,
        )

    async def record_pdb_intent(self, sequence_hash: str, mapping: SiftsMapping) -> None:
        """
        Record that this protein's structure is a specific RCSB PDB entry,
        persisting its SIFTS UniProt-numbering map. Called at resolve time
        for PDB inputs. Idempotent; the RCSB file is fetched later, lazily.
        """
        sifts_uri = self.store.write(
            sequence_hash, "sifts.json", mapping.to_json().encode("utf-8")
        )
        stmt = pg_insert(Structure).values(
            sequence_hash=sequence_hash,
            provider="rcsb",
            pdb_id=mapping.pdb_id,
            sifts_map_uri=sifts_uri,
        )
        # Experimental beats predicted: if a row already exists it's left alone,
        # UNLESS it's a predicted AlphaFold model — a PDB input is an explicit
        # request for the real experimental structure, so we replace it and
        # reset structure_uri/source_url to trigger a fresh RCSB fetch. An
        # existing rcsb row is kept (the WHERE fails), keeping this idempotent.
        stmt = stmt.on_conflict_do_update(
            index_elements=["sequence_hash"],
            set_={
                "provider": stmt.excluded.provider,
                "pdb_id": stmt.excluded.pdb_id,
                "sifts_map_uri": stmt.excluded.sifts_map_uri,
                "structure_uri": None,
                "source_url": None,
            },
            where=(Structure.provider == "alphafold"),
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def _fetch_rcsb_into(self, row: Structure) -> StructureRecord | None:
        assert row.pdb_id is not None, "rcsb row must carry a pdb_id to fetch"
        try:
            data, source_url = await self._require_client().fetch_rcsb(row.pdb_id)
        except StructureNotFound:
            return None
        uri = self.store.write(row.sequence_hash, "pdb", data)
        await self.session.execute(
            update(Structure)
            .where(Structure.sequence_hash == row.sequence_hash)
            .values(structure_uri=uri, source_url=source_url)
        )
        await self.session.commit()
        return StructureRecord(
            sequence_hash=row.sequence_hash,
            provider="rcsb",
            fmt="pdb",
            source_url=source_url,
            structure_uri=uri,
        )

    async def read_file(self, sequence_hash: str) -> tuple[bytes, str] | None:
        """Return (raw_bytes, format) for a fetched structure, or None."""
        record = await self.get_or_fetch(sequence_hash)
        if record is None:
            return None
        return self.store.read(record.structure_uri), record.fmt

    # --- DSSP structural features (computed in the worker, read anywhere) ---

    def store_features(self, sequence_hash: str, context: StructureContext) -> str:
        """Persist a computed StructureContext as JSON. Returns its URI."""
        return self.store.write(
            sequence_hash, "dssp.json", context.model_dump_json().encode("utf-8")
        )

    def load_features(self, sequence_hash: str) -> StructureContext | None:
        """Read a previously computed StructureContext, or None if absent."""
        uri = self.store.build_uri(sequence_hash, "dssp.json")
        if not self.store.exists(uri):
            return None
        return StructureContext.model_validate_json(self.store.read(uri))

    async def load_sifts_segments(self, sequence_hash: str) -> list[dict] | None:
        """Load the stored SIFTS segments (author->UniProt map) for a protein."""
        row = await self._load_row(sequence_hash)
        if row is None or not row.sifts_map_uri:
            return None
        return json.loads(self.store.read(row.sifts_map_uri))["segments"]

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
        # Callers only reach here once the file has been fetched, so
        # structure_uri is set (it's nullable at the DB level for pending rows).
        uri = row.structure_uri
        assert uri is not None, "_to_record requires a fetched structure_uri"
        fmt = uri.rsplit(".", 1)[-1] if "." in uri else "pdb"
        return StructureRecord(
            sequence_hash=row.sequence_hash,
            provider=row.provider,
            fmt=fmt,
            source_url=row.source_url or "",
            structure_uri=uri,
        )
