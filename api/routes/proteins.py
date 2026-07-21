"""POST /api/v1/proteins/resolve — turn an input into a canonical protein."""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_resolver
from api.services.protein_resolver import ProteinResolver
from contracts.schemas import ResolveRequest, ResolveResponse
from domain.derive import Variant, validate_against_sequence

router = APIRouter()


@router.post("/proteins/resolve", response_model=ResolveResponse)
async def resolve_protein(
    req: ResolveRequest,
    resolver: ProteinResolver = Depends(get_resolver),
) -> ResolveResponse:
    try:
        protein = await resolver.resolve(req.input)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    mutation_valid: bool | None = None
    mutation_error: str | None = None
    if req.mutation:
        try:
            variant = Variant.parse(req.mutation)
            validate_against_sequence(variant, protein.sequence)
            mutation_valid = True
        except ValueError as e:
            mutation_valid = False
            mutation_error = str(e)

    return ResolveResponse(
        sequence_hash=protein.sequence_hash,
        length=len(protein.sequence),
        uniprot_id=protein.uniprot_id,
        coordinate_system=protein.coordinate_system,
        source=protein.source,
        has_structure=protein.structure_ref is not None,
        mutation_valid=mutation_valid,
        mutation_error=mutation_error,
    )
