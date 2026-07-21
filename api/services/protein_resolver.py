"""
The ProteinResolver service — takes any input format, does the network
work, returns a ResolvedProtein plus persists it in the proteins table.
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.sifts_client import SiftsClient, SiftsMapping, SiftsNotFound
from api.services.structure_service import StructureService
from api.services.uniprot_client import UniProtClient, UniProtNotFound
from db.models import Protein
from domain.resolve import (
    ResolvedProtein,
    StructureRef,
    build_resolved_protein,
    classify_input,
    clean_fasta,
)


class ProteinResolver:
    def __init__(
        self,
        session: AsyncSession,
        uniprot: UniProtClient,
        sifts: SiftsClient | None = None,
        structures: StructureService | None = None,
    ) -> None:
        self.session = session
        self.uniprot = uniprot
        # Only required for PDB-ID inputs (SIFTS mapping + structure intent).
        self.sifts = sifts
        self.structures = structures

    async def resolve(self, raw_input: str) -> ResolvedProtein:
        kind = classify_input(raw_input)
        mapping: SiftsMapping | None = None

        if kind == "uniprot_id":
            protein = await self._resolve_uniprot(raw_input.strip().upper())
        elif kind == "name":
            accession = await self.uniprot.search_by_gene_name(raw_input.strip())
            protein = await self._resolve_uniprot(accession)
        elif kind == "fasta":
            sequence = clean_fasta(raw_input)
            protein = build_resolved_protein(
                sequence=sequence,
                coordinate_system="fasta",
                uniprot_id=None,
                structure_ref=None,
                source="user_fasta",
            )
        elif kind == "pdb_id":
            protein, mapping = await self._resolve_pdb(raw_input.strip())
        else:
            raise ValueError(f"Could not classify input: {raw_input[:80]}")

        await self._upsert_protein(protein)
        if mapping is not None:
            # Persist the PDB structure intent + SIFTS map after the protein
            # row exists (structures.sequence_hash FKs proteins).
            assert self.structures is not None
            await self.structures.record_pdb_intent(protein.sequence_hash, mapping)
        return protein

    async def _resolve_pdb(self, pdb_id: str) -> tuple[ResolvedProtein, SiftsMapping]:
        """
        Resolve a PDB ID by mapping it to its UniProt entry via SIFTS, then
        scoring the UniProt canonical sequence. Frozen rule #2: a PDB is
        never scored in author numbering — SIFTS gives us the single UniProt
        coordinate system that scores, mutations, and 3D coloring all share.
        """
        if self.sifts is None or self.structures is None:
            raise RuntimeError("PDB resolution requires a SiftsClient and StructureService")

        try:
            mapping = await self.sifts.map_to_uniprot(pdb_id)
        except SiftsNotFound:
            raise ValueError(
                f"PDB {pdb_id} has no UniProt SIFTS mapping; cannot resolve to canonical numbering"
            )

        try:
            sequence, _ = await self.uniprot.fetch_sequence(mapping.uniprot_accession)
        except UniProtNotFound:
            raise ValueError(
                f"PDB {pdb_id} maps to UniProt {mapping.uniprot_accession}, "
                "but that entry could not be fetched"
            )

        protein = build_resolved_protein(
            sequence=sequence,
            coordinate_system="uniprot",
            uniprot_id=mapping.uniprot_accession,
            structure_ref=StructureRef(provider="rcsb", identifier=mapping.pdb_id),
            source=f"pdb:{mapping.pdb_id} (uniprot:{mapping.uniprot_accession})",
        )
        return protein, mapping

    async def _resolve_uniprot(self, accession: str) -> ResolvedProtein:
        try:
            sequence, source = await self.uniprot.fetch_sequence(accession)
        except UniProtNotFound:
            raise ValueError(f"UniProt accession not found: {accession}")

        return build_resolved_protein(
            sequence=sequence,
            coordinate_system="uniprot",
            uniprot_id=accession,
            structure_ref=StructureRef(provider="alphafold", identifier=accession),
            source=source,
        )

    async def _upsert_protein(self, protein: ResolvedProtein) -> None:
        stmt = (
            pg_insert(Protein)
            .values(
                sequence_hash=protein.sequence_hash,
                sequence=protein.sequence,
                length=len(protein.sequence),
                uniprot_id=protein.uniprot_id,
                source=protein.source,
            )
            .on_conflict_do_nothing(index_elements=["sequence_hash"])
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def load_by_hash(self, sequence_hash: str) -> ResolvedProtein | None:
        result = await self.session.execute(
            select(Protein).where(Protein.sequence_hash == sequence_hash)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return build_resolved_protein(
            sequence=row.sequence,
            coordinate_system="uniprot" if row.uniprot_id else "fasta",
            uniprot_id=row.uniprot_id,
            structure_ref=(
                StructureRef(provider="alphafold", identifier=row.uniprot_id)
                if row.uniprot_id
                else None
            ),
            source=row.source,
        )
