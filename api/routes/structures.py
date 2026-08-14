"""
Structure endpoints — fetch-on-first-request 3D models for the viewer.

    GET /api/v1/structures/{sequence_hash}        -> StructureInfo metadata
    GET /api/v1/structures/{sequence_hash}/file   -> raw structure bytes

Both trigger a one-time fetch from AlphaFold/RCSB if the structure isn't
already cached; subsequent calls read the stored copy.
"""

from fastapi import APIRouter, Depends, HTTPException, Response

from api.deps import get_structure_service
from api.services.structure_service import StructureService
from contracts.schemas import SiftsSegment, StructureInfo

router = APIRouter()


def _file_url(sequence_hash: str, provider: str) -> str:
    return f"/api/v1/structures/{sequence_hash}/file?provider={provider}"


@router.get("/structures/{sequence_hash}", response_model=StructureInfo)
async def get_structure(
    sequence_hash: str,
    provider: str | None = None,
    structures: StructureService = Depends(get_structure_service),
) -> StructureInfo:
    # `provider` reflects what the visitor actually searched: a PDB id asks
    # for that experimental entry, anything else gets the full-length
    # prediction. Unset means "whatever suits", which prefers AlphaFold.
    if provider not in (None, "alphafold", "rcsb"):
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    record = await structures.get_or_fetch(sequence_hash, provider)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No structure available for {sequence_hash} (unknown protein or FASTA-only input)",
        )
    # The viewer colours residues by UniProt position. An experimental entry
    # numbers its residues however the depositors did, so without this map a
    # cropped structure is coloured with a constant offset — 1TUP's p53 DBD
    # runs 1-219 in the file but 94-312 in UniProt.
    segments = await structures.load_sifts_segments(
        sequence_hash, record.provider
    ) or []

    return StructureInfo(
        sequence_hash=record.sequence_hash,
        provider=record.provider,
        format=record.fmt,
        source_url=record.source_url,
        file_url=_file_url(sequence_hash, record.provider),
        sifts_segments=[SiftsSegment(**s) for s in segments],
    )


@router.get("/structures/{sequence_hash}/file")
async def get_structure_file(
    sequence_hash: str,
    provider: str | None = None,
    structures: StructureService = Depends(get_structure_service),
) -> Response:
    result = await structures.read_file(sequence_hash, provider)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No structure available for {sequence_hash}")
    data, fmt = result
    media_type = "chemical/x-pdb" if fmt == "pdb" else "application/octet-stream"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{sequence_hash}.{fmt}"'},
    )
