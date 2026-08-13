"""POST /api/v1/proteins/resolve — turn an input into a canonical protein."""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_resolver
from api.services.protein_resolver import ProteinNotFound, ProteinResolver
from contracts.schemas import MutationSuggestion, ResolveRequest, ResolveResponse
from domain.derive import Variant, validate_against_sequence
from domain.repair import explain_and_suggest, explain_parse_failure

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
    except ProteinNotFound as e:
        # Well-formed request, no such protein. Not a server fault, and not a
        # malformed input either. Structured so the client can render the
        # alternatives as one-click retries.
        raise HTTPException(
            status_code=404,
            detail={
                "message": (
                    f"Couldn't find a protein matching that. {str(e)}"
                    if not e.candidates
                    else "Couldn't find that exactly. Did you mean one of these?"
                ),
                "suggestions": [
                    {
                        "input": accession,
                        "label": symbol or accession,
                        "reason": name or f"UniProt {accession}",
                    }
                    for accession, symbol, name in e.candidates
                ],
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    mutation_valid: bool | None = None
    mutation_error: str | None = None
    explanation: str | None = None
    suggestions: list[MutationSuggestion] = []
    if req.mutation:
        try:
            variant = Variant.parse(req.mutation)
        except ValueError as e:
            # Couldn't even be read as a mutation — explain the format rather
            # than surfacing a parser message.
            mutation_valid = False
            mutation_error = str(e)
            explanation = explain_parse_failure(req.mutation)
        else:
            try:
                validate_against_sequence(variant, protein.sequence)
                mutation_valid = True
            except ValueError as e:
                # Parsed fine but doesn't fit this sequence. We hold the real
                # sequence, so the correction can be computed rather than guessed.
                mutation_valid = False
                mutation_error = str(e)
                explanation, fixes = explain_and_suggest(variant, protein.sequence)
                suggestions = [
                    MutationSuggestion(mutation=f.mutation, reason=f.reason)
                    for f in fixes
                ]

    return ResolveResponse(
        sequence_hash=protein.sequence_hash,
        length=len(protein.sequence),
        uniprot_id=protein.uniprot_id,
        coordinate_system=protein.coordinate_system,
        source=protein.source,
        has_structure=protein.structure_ref is not None,
        mutation_valid=mutation_valid,
        mutation_error=mutation_error,
        mutation_explanation=explanation,
        mutation_suggestions=suggestions,
    )
