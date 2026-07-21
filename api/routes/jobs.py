"""POST /api/v1/jobs and GET /api/v1/jobs/{id} — job lifecycle endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_job_service
from api.services.job_service import JobService
from contracts.schemas import (
    CreateJobRequest,
    CreateJobResponse,
    JobStatusResponse,
)

router = APIRouter()


@router.post("/jobs", response_model=CreateJobResponse)
async def create_job(
    req: CreateJobRequest,
    jobs: JobService = Depends(get_job_service),
) -> CreateJobResponse:
    job_id, status, cached = await jobs.create_or_reuse(
        sequence_hash=req.sequence_hash, model_id=req.model_id
    )
    return CreateJobResponse(job_id=job_id, status=status, cached=cached)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    jobs: JobService = Depends(get_job_service),
) -> JobStatusResponse:
    result = await jobs.get_status(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    status, error = result
    return JobStatusResponse(job_id=job_id, status=status, error=error)
