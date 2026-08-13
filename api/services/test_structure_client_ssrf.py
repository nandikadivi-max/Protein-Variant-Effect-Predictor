"""
The structure downloader follows a URL that AlphaFold's API supplies, rather
than one we construct, so it is worth pinning where it may point.
"""

import pytest

from api.services.structure_client import StructureClient, StructureNotFound


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",   # cloud metadata service
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://localhost:8000/api/v1/jobs",
        "http://127.0.0.1:5432/",
        "file:///etc/passwd",
        "https://evil.example.com/AF-P04637-F1-model_v6.pdb",
        # Lookalike host: the real one is a suffix, which a naive check misses.
        "https://alphafold.ebi.ac.uk.evil.example.com/x.pdb",
    ],
)
async def test_refuses_unexpected_hosts(url: str) -> None:
    client = StructureClient()
    try:
        with pytest.raises(StructureNotFound, match="unexpected host"):
            await client._download(url, "test")
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "url",
    [
        "https://alphafold.ebi.ac.uk/files/AF-P04637-F1-model_v6.pdb",
        "https://files.rcsb.org/download/1crn.pdb",
    ],
)
def test_permits_the_real_sources(url: str) -> None:
    from urllib.parse import urlparse

    client = StructureClient()
    assert urlparse(url).hostname in client._allowed_hosts()
