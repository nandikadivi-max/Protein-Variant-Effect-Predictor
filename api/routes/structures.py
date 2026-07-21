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
from contracts.schemas import StructureInfo

router = APIRouter()


def _file_url(sequence_hash: str) -> str:
    return f"/api/v1/structures/{sequence_hash}/file"


@router.get("/structures/{sequence_hash}", response_model=StructureInfo)
async def get_structure(
    sequence_hash: str,
    structures: StructureService = Depends(get_structure_service),
) -> StructureInfo:
    record = await structures.get_or_fetch(sequence_hash)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No structure available for {sequence_hash} (unknown protein or FASTA-only input)",
        )
    return StructureInfo(
        sequence_hash=record.sequence_hash,
        provider=record.provider,
        format=record.fmt,
        source_url=record.source_url,
        file_url=_file_url(sequence_hash),
    )


@router.get("/structures/{sequence_hash}/file")
async def get_structure_file(
    sequence_hash: str,
    structures: StructureService = Depends(get_structure_service),
) -> Response:
    result = await structures.read_file(sequence_hash)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No structure available for {sequence_hash}")
    data, fmt = result
    media_type = "chemical/x-pdb" if fmt == "pdb" else "application/octet-stream"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{sequence_hash}.{fmt}"'},
    )
