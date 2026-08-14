"""POST /api/v1/proteins/resolve — turn an input into a canonical protein."""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_protein_catalog, get_resolver
from api.services.protein_catalog import ProteinCatalog
from api.services.protein_resolver import ProteinNotFound, ProteinResolver
from config import get_settings
from contracts.schemas import (
    CachedProtein,
    MutationSuggestion,
    ResolveRequest,
    ResolveResponse,
)
from domain.derive import Variant, validate_against_sequence
from domain.repair import explain_and_suggest, explain_parse_failure

router = APIRouter()


@router.get("/proteins/cached", response_model=list[CachedProtein])
async def cached_proteins(
    limit: int = 12,
    catalog: ProteinCatalog = Depends(get_protein_catalog),
) -> list[CachedProtein]:
    """
    Proteins already scored, and so instant to open.

    The set grows by itself as people use the tool. Pasted sequences are
    excluded — see ProteinCatalog for why that is a rule rather than a
    detail.
    """
    entries = await catalog.scored(
        model_id=get_settings().default_model_id,
        limit=max(1, min(limit, 24)),
    )
    return [
        CachedProtein(
            uniprot_id=e.uniprot_id,
            gene=e.gene,
            name=e.name,
            length=e.length,
            sequence_hash=e.sequence_hash,
        )
        for e in entries
    ]


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
        structure_provider=(
            protein.structure_ref.provider if protein.structure_ref else None
        ),
        mutation_valid=mutation_valid,
        mutation_error=mutation_error,
        mutation_explanation=explanation,
        mutation_suggestions=suggestions,
    )
