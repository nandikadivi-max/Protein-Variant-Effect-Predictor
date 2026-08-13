"""
Async UniProt REST client. Fetches canonical isoform sequences for a
UniProt accession and resolves gene names to an accession.
"""

import difflib

import httpx

from config import get_settings


def _echo_safe(value: str, limit: int = 60) -> str:
    """
    Make user input safe to quote back in an error message.

    Error strings reach both the client and the application log. Echoing raw
    input meant a newline in the query produced a message spanning several
    lines, which forges log entries, and an unbounded value made the message
    as large as the request. Control characters are stripped and the whole
    thing is truncated.
    """
    cleaned = "".join(ch for ch in value if ch.isprintable())
    return cleaned[:limit] + "…" if len(cleaned) > limit else cleaned


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
        params = {"query": search_query, "format": "json", "size": "1", "fields": "accession"}
        response = await self._client.get(url, params=params)
        response.raise_for_status()

        results = response.json().get("results", [])
        if not results:
            raise UniProtNotFound(
                f"No reviewed UniProt entry found for gene '{_echo_safe(query)}'"
            )
        return results[0]["primaryAccession"]

    async def suggest_similar(
        self, query: str, organism_id: int = 9606, limit: int = 3
    ) -> list[tuple[str, str, str]]:
        """
        Best-effort "did you mean" candidates for a name that resolved to
        nothing, as (accession, gene symbol, protein name).

        Deliberately a *loose* search, unlike search_by_gene_name, which is
        exact on purpose to avoid TP53 matching TP53RK. Here recall is what
        matters: these are only ever offered as suggestions the user picks
        from, never resolved automatically.
        """
        cleaned = "".join(ch for ch in query if ch.isalnum() or ch in "- ").strip()
        if not cleaned:
            return []

        # Free-text first: this is what turns "hemoglobin beta" into HBB.
        hits = await self._search(
            f"{cleaned} AND organism_id:{organism_id} AND reviewed:true", limit
        )
        if hits:
            return hits

        # Nothing matched, so the input is likely a misspelt symbol. UniProt
        # does token matching, not fuzzy matching, so "TP54" finds nothing at
        # all. Search the stem with a wildcard and rank what comes back by
        # similarity to what was typed — otherwise "TP5*" answers TP53BP1
        # before TP53.
        stem = cleaned.split()[0]
        if len(stem) < 3 or not stem.isalnum():
            return []
        wide = await self._search(
            f"gene:{stem[:-1]}* AND organism_id:{organism_id} AND reviewed:true",
            limit=40,
        )
        if not wide:
            return []

        by_symbol = {symbol.upper(): (acc, symbol, name) for acc, symbol, name in wide if symbol}
        close = difflib.get_close_matches(
            stem.upper(), list(by_symbol), n=limit, cutoff=0.5
        )
        return [by_symbol[sym] for sym in close]

    async def _search(self, query: str, limit: int) -> list[tuple[str, str, str]]:
        """Run one UniProt search, returning (accession, symbol, protein name)."""
        url = f"{self._settings.uniprot_api_base}/uniprotkb/search"
        params = {
            "query": query,
            "format": "json",
            "size": str(limit),
            "fields": "accession,gene_primary,protein_name",
        }
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            results = response.json().get("results", [])
        except Exception:  # noqa: BLE001
            return []  # suggestions are a nicety; never fail the request over them

        out: list[tuple[str, str, str]] = []
        for entry in results:
            accession = entry.get("primaryAccession")
            genes = entry.get("genes") or []
            symbol = (genes[0].get("geneName", {}) or {}).get("value", "") if genes else ""
            name = (
                (entry.get("proteinDescription", {}) or {})
                .get("recommendedName", {})
                .get("fullName", {})
                .get("value", "")
            )
            if accession:
                out.append((accession, symbol, name))
        return out
