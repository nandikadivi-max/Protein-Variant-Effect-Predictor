"""
Integration tests for the UniProt client. These hit the real UniProt API.

Run explicitly:
    pytest api/services/test_uniprot_client.py -v -m network
"""

import pytest

from api.services.uniprot_client import UniProtClient, UniProtNotFound

pytestmark = pytest.mark.network

TP53_PREFIX = "MEEPQSDPSVEPPLSQETFSDLWKLLPENNVLSPLPSQAM"


@pytest.mark.asyncio
async def test_fetch_tp53_by_accession():
    client = UniProtClient()
    try:
        sequence, source = await client.fetch_sequence("P04637")
    finally:
        await client.aclose()

    assert sequence.startswith(TP53_PREFIX)
    assert source == "uniprot:P04637"
    assert 380 < len(sequence) < 410


@pytest.mark.asyncio
async def test_search_gene_tp53_returns_p04637():
    client = UniProtClient()
    try:
        accession = await client.search_by_gene_name("TP53")
    finally:
        await client.aclose()
    assert accession == "P04637"


@pytest.mark.asyncio
async def test_fetch_nonexistent_accession_raises():
    client = UniProtClient()
    try:
        with pytest.raises(UniProtNotFound):
            await client.fetch_sequence("ZZZZZZ")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_suggest_similar_recovers_from_a_typo():
    """
    UniProt does token matching, not fuzzy matching, so a misspelt symbol
    finds nothing at all. The stem-wildcard fallback plus local similarity
    ranking is what turns TP54 into TP53 rather than TP53BP1.
    """
    client = UniProtClient()
    try:
        symbols = [s for _, s, _ in await client.suggest_similar("TP54")]
        assert "TP53" in symbols
        assert symbols[0] == "TP53", f"TP53 should rank first, got {symbols}"

        symbols = [s for _, s, _ in await client.suggest_similar("BRCA3")]
        assert {"BRCA1", "BRCA2"} & set(symbols)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_suggest_similar_handles_free_text_and_gives_up_quietly():
    client = UniProtClient()
    try:
        symbols = [s for _, s, _ in await client.suggest_similar("hemoglobin beta")]
        assert "HBB" in symbols
        # Genuine nonsense must produce nothing rather than a confident guess.
        assert await client.suggest_similar("xyzzy123qqq") == []
        assert await client.suggest_similar("   ") == []
    finally:
        await client.aclose()
