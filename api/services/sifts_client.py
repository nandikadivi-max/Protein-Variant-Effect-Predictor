"""
SIFTS client — maps a PDB entry to its UniProt entry and residue numbering.

Frozen architectural rule #2 (one coordinate system): a PDB structure may
NOT be scored in its own author numbering. It must carry an explicit SIFTS
map to UniProt canonical numbering, so that a scored position, a mutation
string, and a 3D-colored residue always refer to the same coordinate. This
client produces that map from the PDBe SIFTS API.

For a residue with PDB author number `a` inside a segment, its UniProt
position is `a + (unp_start - author_start)`.
"""

import json
from dataclasses import asdict, dataclass

import httpx

from config import get_settings

PDBE_SIFTS_BASE = "https://www.ebi.ac.uk/pdbe/api/mappings/uniprot"


class SiftsNotFound(Exception):
    """Raised when a PDB entry has no UniProt SIFTS mapping."""


@dataclass(frozen=True)
class SiftsSegment:
    chain_id: str
    pdb_start: int   # author residue number
    pdb_end: int
    unp_start: int   # UniProt residue number
    unp_end: int


@dataclass(frozen=True)
class SiftsMapping:
    pdb_id: str
    uniprot_accession: str
    uniprot_name: str | None
    segments: tuple[SiftsSegment, ...]

    def to_json(self) -> str:
        return json.dumps(
            {
                "pdb_id": self.pdb_id,
                "uniprot_accession": self.uniprot_accession,
                "uniprot_name": self.uniprot_name,
                "segments": [asdict(s) for s in self.segments],
            }
        )


class SiftsClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=self._settings.http_timeout_seconds,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def map_to_uniprot(self, pdb_id: str) -> SiftsMapping:
        """
        Resolve a PDB ID to its primary UniProt entry and residue mapping.

        When an entry maps to several UniProt entries (a complex of distinct
        proteins), we pick the one covering the most residues — the dominant
        chain the user most likely means. Raises SiftsNotFound otherwise.
        """
        pdb_id = pdb_id.lower()
        url = f"{PDBE_SIFTS_BASE}/{pdb_id}"
        response = await self._client.get(url)
        if response.status_code == 404:
            raise SiftsNotFound(f"No SIFTS mapping for PDB {pdb_id}")
        response.raise_for_status()

        uniprot_block = response.json().get(pdb_id, {}).get("UniProt", {})
        if not uniprot_block:
            raise SiftsNotFound(f"PDB {pdb_id} has no UniProt mapping")

        best_acc, best_data, best_coverage = None, None, -1
        for accession, data in uniprot_block.items():
            covered = sum(
                m["unp_end"] - m["unp_start"] + 1 for m in data.get("mappings", [])
            )
            if covered > best_coverage:
                best_acc, best_data, best_coverage = accession, data, covered

        if best_acc is None:
            raise SiftsNotFound(f"PDB {pdb_id} has no UniProt mapping")

        segments = tuple(
            SiftsSegment(
                chain_id=m["chain_id"],
                pdb_start=m["start"]["author_residue_number"],
                pdb_end=m["end"]["author_residue_number"],
                unp_start=m["unp_start"],
                unp_end=m["unp_end"],
            )
            for m in best_data.get("mappings", [])
        )
        return SiftsMapping(
            pdb_id=pdb_id,
            uniprot_accession=best_acc,
            uniprot_name=best_data.get("identifier") or best_data.get("name"),
            segments=segments,
        )
