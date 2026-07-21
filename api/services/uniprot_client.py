"""
Async UniProt REST client. Fetches canonical isoform sequences for a
UniProt accession and resolves gene names to an accession.
"""

import httpx

from config import get_settings


class UniProtNotFound(Exception):
    """Raised when a UniProt query returns no matching reviewed entry."""


class UniProtClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=self._settings.http_timeout_seconds)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_sequence(self, accession: str) -> tuple[str, str]:
        """
        Fetch the canonical sequence for a UniProt accession.
        Returns (sequence, source_label). Raises UniProtNotFound on any 4xx.
        """
        url = f"{self._settings.uniprot_api_base}/uniprotkb/{accession}.fasta"
        response = await self._client.get(url)
        if 400 <= response.status_code < 500:
            raise UniProtNotFound(f"UniProt accession not found: {accession}")
        response.raise_for_status()

        text = response.text
        lines = [line for line in text.strip().splitlines() if not line.startswith(">")]
        sequence = "".join(lines).strip().upper()
        if not sequence:
            raise UniProtNotFound(f"UniProt returned empty sequence for {accession}")
        return sequence, f"uniprot:{accession}"

    async def search_by_gene_name(self, query: str, organism_id: int = 9606) -> str:
        """
        Resolve a gene name to a reviewed UniProt accession via exact
        gene symbol match. Defaults to human (taxon 9606); pass
        organism_id=0 to skip that filter.

        gene_exact ONLY, not protein_name — OR-ing in a loose protein_name
        match caused false hits (e.g. TP53 -> TP53RK).
        """
        parts = [f'gene_exact:"{query}"', "reviewed:true"]
        if organism_id:
            parts.append(f"organism_id:{organism_id}")
        search_query = " AND ".join(parts)

        url = f"{self._settings.uniprot_api_base}/uniprotkb/search"
        params = {"query": search_query, "format": "json", "size": 1, "fields": "accession"}
        response = await self._client.get(url, params=params)
        response.raise_for_status()

        results = response.json().get("results", [])
        if not results:
            raise UniProtNotFound(f"No reviewed UniProt entry found for gene '{query}'")
        return results[0]["primaryAccession"]
