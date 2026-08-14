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

from sqlalchemy import case, select, update
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

    async def get_or_fetch(
        self, sequence_hash: str, provider: str | None = None
    ) -> StructureRecord | None:
        """
        Return a structure record, fetching + persisting it on first request.

        A protein may now hold both a predicted model and an experimental
        entry, so `provider` says which the caller wants — normally taken from
        what the visitor actually searched for. Left unset it prefers the
        AlphaFold model, because that covers the whole sequence while a
        crystal structure usually covers a fragment.

        Returns None when the protein is unknown or has no structure source
        (FASTA-only input).
        """
        existing = await self._load_row(sequence_hash, provider)
        if existing is not None:
            if existing.structure_uri:
                return self._to_record(existing)
            # A recorded-but-not-yet-fetched PDB intent: download it now.
            if existing.provider == "rcsb" and existing.pdb_id:
                return await self._fetch_rcsb_into(existing)
            return None

        # Asked for an experimental structure we have no record of: there is
        # nothing to fetch, since the PDB id only arrives via a resolve.
        if provider == "rcsb":
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

        uri = self.store.write(sequence_hash, "alphafold.pdb", data)
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
        # No longer competes with the predicted model: the two are separate
        # rows now, so recording an experimental entry cannot take the
        # AlphaFold structure away from everyone else. Re-resolving the same
        # PDB id refreshes its SIFTS map and re-triggers the file fetch.
        stmt = stmt.on_conflict_do_update(
            index_elements=["sequence_hash", "provider"],
            set_={
                "pdb_id": stmt.excluded.pdb_id,
                "sifts_map_uri": stmt.excluded.sifts_map_uri,
            },
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def _fetch_rcsb_into(self, row: Structure) -> StructureRecord | None:
        assert row.pdb_id is not None, "rcsb row must carry a pdb_id to fetch"
        try:
            data, source_url = await self._require_client().fetch_rcsb(row.pdb_id)
        except StructureNotFound:
            return None
        # Provider-scoped object key, and a provider-scoped UPDATE. Both
        # matter now that a protein has more than one structure: a bare
        # sequence_hash would make the experimental file overwrite the
        # prediction in storage, and stamp its URI onto the prediction's row.
        uri = self.store.write(row.sequence_hash, "rcsb.pdb", data)
        await self.session.execute(
            update(Structure)
            .where(
                Structure.sequence_hash == row.sequence_hash,
                Structure.provider == "rcsb",
            )
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

    async def read_file(
        self, sequence_hash: str, provider: str | None = None
    ) -> tuple[bytes, str] | None:
        """Return (raw_bytes, format) for a fetched structure, or None."""
        record = await self.get_or_fetch(sequence_hash, provider)
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

    async def load_sifts_segments(
        self, sequence_hash: str, provider: str | None = None
    ) -> list[dict] | None:
        """
        Load the stored SIFTS segments (author->UniProt map) for a protein.

        Segments are repaired on the way out. PDBe sometimes omits the author
        residue number at one end — 1TUP does — and maps stored before that
        was handled carry a null pdb_end, which raises inside the range
        comparison every consumer performs. A segment is contiguous, so the
        end is reconstructed from the start plus the UniProt span; anything
        still incoherent is dropped rather than allowed to mis-map residues.
        """
        row = await self._load_row(sequence_hash, provider)
        if row is None or not row.sifts_map_uri:
            return None
        raw = json.loads(self.store.read(row.sifts_map_uri))["segments"]

        repaired: list[dict] = []
        for seg in raw:
            start, unp_start, unp_end = (
                seg.get("pdb_start"),
                seg.get("unp_start"),
                seg.get("unp_end"),
            )
            if start is None or unp_start is None or unp_end is None:
                continue
            end = seg.get("pdb_end")
            if end is None:
                end = start + (unp_end - unp_start)
            repaired.append({**seg, "pdb_start": start, "pdb_end": end})
        return repaired

    async def _load_row(
        self, sequence_hash: str, provider: str | None = None
    ) -> Structure | None:
        """
        The stored row for this protein, optionally for a specific provider.

        With no preference, an AlphaFold model wins over an experimental one:
        it spans the whole sequence, so it matches the full-length heatmap and
        DSSP track beside it, whereas a crystal structure usually covers a
        fragment. A visitor who asked for a PDB id gets that entry because the
        caller passes the preference through.
        """
        stmt = select(Structure).where(Structure.sequence_hash == sequence_hash)
        if provider is not None:
            stmt = stmt.where(Structure.provider == provider)
        else:
            stmt = stmt.order_by(
                case((Structure.provider == "alphafold", 0), else_=1)
            )
        result = await self.session.execute(stmt)
        return result.scalars().first()

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
            .on_conflict_do_nothing(index_elements=["sequence_hash", "provider"])
        )
        await self.session.execute(stmt)
        await self.session.commit()

    @staticmethod
    def _to_record(row: Structure) -> StructureRecord:
        # Callers only reach here once the file has been fetched, so
        # structure_uri is set (it's nullable at the DB level for pending rows).
        uri = row.structure_uri
        assert uri is not None, "_to_record requires a fetched structure_uri"
        # URIs are provider-scoped ("...alphafold.pdb"), so take the final
        # extension rather than everything after the first dot.
        fmt = uri.rsplit(".", 1)[-1] if "." in uri else "pdb"
        return StructureRecord(
            sequence_hash=row.sequence_hash,
            provider=row.provider,
            fmt=fmt,
            source_url=row.source_url or "",
            structure_uri=uri,
        )
