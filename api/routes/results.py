"""GET /api/v1/results/{sequence_hash} — retrieve computed results."""

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_results_service
from api.services.results_service import ResultsService
from config import get_settings
from contracts.schemas import ScoreResult

router = APIRouter()


@router.get("/results/{sequence_hash}", response_model=ScoreResult)
async def get_results(
    sequence_hash: str,
    model_id: str = Query(default=None),
    mutation: str | None = Query(default=None),
    results: ResultsService = Depends(get_results_service),
) -> ScoreResult:
    settings = get_settings()
    resolved_model_id = model_id or settings.default_model_id

    try:
        result = await results.build_result(
            sequence_hash=sequence_hash, model_id=resolved_model_id, mutation=mutation
        )
    except ValueError as e:
        # Mutation validation failure -> 400
        raise HTTPException(status_code=400, detail=str(e))

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No result yet for ({sequence_hash}, {resolved_model_id}). "
                "Create a job first or wait for it to finish."
            ),
        )
    return result
