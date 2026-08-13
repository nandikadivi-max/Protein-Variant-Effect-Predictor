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


def _segment_from_mapping(m: dict) -> "SiftsSegment | None":
    """
    One SIFTS mapping entry -> a segment, or None if it can't be trusted.

    PDBe does not always give an author residue number at both ends: 1TUP,
    the canonical p53 structure, comes back with a null author number for the
    end of its mapping. Taking that at face value stored pdb_end=None, which
    then raised inside the range comparison in _map_to_uniprot — swallowed by
    the best-effort wrapper around feature computation, so it looked like the
    structure simply had no features.

    A SIFTS segment is contiguous by definition, so a missing end can be
    reconstructed from the start plus the UniProt span. A missing start
    cannot, and that segment is dropped rather than guessed at.
    """
    start = m.get("start", {}).get("author_residue_number")
    end = m.get("end", {}).get("author_residue_number")
    unp_start, unp_end = m.get("unp_start"), m.get("unp_end")
    if start is None or unp_start is None or unp_end is None:
        return None
    if end is None:
        end = start + (unp_end - unp_start)
    return SiftsSegment(
        chain_id=m["chain_id"],
        pdb_start=start,
        pdb_end=end,
        unp_start=unp_start,
        unp_end=unp_end,
    )


def _segments_from_mappings(mappings: list[dict]) -> tuple["SiftsSegment", ...]:
    """
    Build the author->UniProt segments for every chain PDBe reports.

    Chains of the same protein are numbered alike, which matters because PDBe
    often reports the author numbering for only one of them. In 1TUP the p53
    trimer maps chains A, B and C to UniProt 94-312, but only chain A carries
    an author residue number — so taking the mappings at face value colours
    one chain and leaves two identical copies blank, which reads as a bug.
    Any chain whose numbering is stated establishes the offset for the rest.
    """
    parsed = [(m, _segment_from_mapping(m)) for m in mappings]
    known = [seg for _, seg in parsed if seg is not None]

    # All chains here describe the same protein, so one offset covers them.
    offset = (known[0].unp_start - known[0].pdb_start) if known else None

    segments: list[SiftsSegment] = []
    for mapping, seg in parsed:
        if seg is not None:
            segments.append(seg)
            continue
        # Reconstructable only if the UniProt span is known and some sibling
        # chain told us how this entry numbers its residues.
        unp_start, unp_end = mapping.get("unp_start"), mapping.get("unp_end")
        chain_id = mapping.get("chain_id")
        if offset is None or unp_start is None or unp_end is None or not chain_id:
            continue
        segments.append(
            SiftsSegment(
                chain_id=chain_id,
                pdb_start=unp_start - offset,
                pdb_end=unp_end - offset,
                unp_start=unp_start,
                unp_end=unp_end,
            )
        )
    return tuple(segments)


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

        if best_acc is None or best_data is None:
            raise SiftsNotFound(f"PDB {pdb_id} has no UniProt mapping")

        segments = _segments_from_mappings(best_data.get("mappings", []))
        return SiftsMapping(
            pdb_id=pdb_id,
            uniprot_accession=best_acc,
            uniprot_name=best_data.get("identifier") or best_data.get("name"),
            segments=segments,
        )
