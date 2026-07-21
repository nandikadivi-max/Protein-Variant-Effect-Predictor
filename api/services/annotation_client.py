"""
Async client for the EBI Proteins variation API.

One call returns every catalogued variant for a UniProt accession, each
tagged with clinical significance (aggregated from ClinVar, Ensembl,
UniProt and NCI-TCGA) and predictor scores (SIFT/PolyPhen). This fits the
project's "fetch once per protein, derive per variant" grain — the caller
filters the returned list to the specific mutation.

Note on AlphaMissense: it is deliberately NOT sourced here. No free
per-variant REST endpoint exposes AlphaMissense; it ships only as a ~1GB
bulk dataset. `VariantPrediction` is generic so an AlphaMissense provider
can be added later without touching this contract.
"""

import httpx

from config import get_settings

# Module-level cache shared across requests in the long-lived API process.
# The per-protein variant list is large (TP53 is ~1-2MB / 3.5k variants) and
# rarely changes, so caching it turns repeat result lookups from a multi-second
# EBI round trip into an instant hit. Simple FIFO eviction keeps memory bounded.
_VARIANT_CACHE: dict[str, list[dict]] = {}
_CACHE_MAX = 128


class AnnotationClient:
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

    async def fetch_variants(self, uniprot_accession: str) -> list[dict]:
        """Return the raw variant feature list for an accession ([] if none)."""
        cached = _VARIANT_CACHE.get(uniprot_accession)
        if cached is not None:
            return cached

        url = f"{self._settings.proteins_api_base}/variation/{uniprot_accession}"
        response = await self._client.get(url, headers={"Accept": "application/json"})
        # 400 = malformed accession, 404 = valid but unknown. Either way there
        # are simply no variants to annotate with.
        if response.status_code in (400, 404):
            features: list[dict] = []
        else:
            response.raise_for_status()
            features = response.json().get("features", [])

        if len(_VARIANT_CACHE) >= _CACHE_MAX:
            _VARIANT_CACHE.pop(next(iter(_VARIANT_CACHE)))  # evict oldest
        _VARIANT_CACHE[uniprot_accession] = features
        return features
