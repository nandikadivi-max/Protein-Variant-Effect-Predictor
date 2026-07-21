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
