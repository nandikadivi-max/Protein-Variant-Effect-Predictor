"""
Async structure-download client. Pulls a 3D model for a protein from
either AlphaFold DB (predicted, UniProt-numbered) or RCSB (experimental,
PDB-numbered).

We download the PDB format specifically: the Debian `dssp` binary the
worker runs against these files is most reliable on PDB, and Mol* reads
PDB fine for the viewer. mmCIF is the more future-proof choice and can be
swapped in later behind this same interface.
"""

import httpx

from config import get_settings


class StructureNotFound(Exception):
    """Raised when no structure file exists for the requested identifier."""


class StructureClient:
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

    async def fetch_alphafold(self, uniprot_accession: str) -> tuple[bytes, str]:
        """
        Download the AlphaFold predicted structure for a UniProt accession.
        Returns (pdb_bytes, source_url).

        The file URL is resolved through the prediction API so we track
        AlphaFold's current model version automatically instead of baking
        it into the path. Our sequences are capped at 1022 residues, so the
        first prediction entry (fragment 1) always covers them.
        """
        api_url = f"{self._settings.alphafold_api_base}/prediction/{uniprot_accession}"
        response = await self._client.get(api_url)
        # 400 = invalid identifier format, 404/422 = valid format but no model.
        # All mean "no structure available" for our purposes.
        if response.status_code in (400, 404, 422):
            raise StructureNotFound(f"No AlphaFold model for {uniprot_accession}")
        response.raise_for_status()

        entries = response.json()
        if not entries or not entries[0].get("pdbUrl"):
            raise StructureNotFound(f"No AlphaFold model for {uniprot_accession}")
        return await self._download(entries[0]["pdbUrl"], uniprot_accession)

    async def fetch_rcsb(self, pdb_id: str) -> tuple[bytes, str]:
        """
        Download an experimental structure from RCSB by PDB ID. Returns
        (pdb_bytes, source_url).
        """
        pdb_id = pdb_id.lower()
        url = f"{self._settings.rcsb_files_base}/{pdb_id}.pdb"
        return await self._download(url, pdb_id)

    async def _download(self, url: str, identifier: str) -> tuple[bytes, str]:
        response = await self._client.get(url)
        if response.status_code == 404:
            raise StructureNotFound(f"No structure at {url}")
        response.raise_for_status()
        content = response.content
        if not content:
            raise StructureNotFound(f"Empty structure file for {identifier} at {url}")
        return content, url
