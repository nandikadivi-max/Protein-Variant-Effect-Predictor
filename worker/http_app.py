"""
HTTP worker entrypoint — the *push* transport, used in production.

Cloud Run only allocates CPU while a request is in flight, and only keeps
an instance alive while it has work. A pull-based worker (ARQ polling
Redis) therefore cannot scale to zero: there is no request to scale on,
so it must run 24/7 with CPU permanently allocated. Doing the scoring
*inside* an HTTP request inverts that — CPU is allocated for exactly as
long as the job runs, and the instance is reclaimed afterwards. An idle
deployment costs nothing.

Two details matter for that to actually work:

1. The model loads lazily on the first `/score`, not at startup. Cloud
   Run's startup probe hits `/health`, which must answer immediately; a
   40s model load in the lifespan would risk failing the probe and
   restart-looping. The first job pays the load, subsequent jobs on the
   same warm instance do not.
2. Scoring runs in a worker thread. `per_position_log_probs` is blocking
   CPU work, and holding the event loop would stall `/health` and make
   Cloud Run consider the container unresponsive mid-job.
"""

import asyncio

from fastapi import FastAPI
from pydantic import BaseModel

from worker.scoring_job import run_scoring

app = FastAPI(title="Protein Variant Effect Predictor Worker", version="0.1.0")

_scorer = None
_scorer_lock = asyncio.Lock()


async def get_scorer():
    """Load ESM-2 once per instance, on first use. The lock keeps two
    concurrent requests from each loading their own multi-GB copy."""
    global _scorer
    if _scorer is None:
        async with _scorer_lock:
            if _scorer is None:
                from worker.scorers.esm2 import ESM2Scorer

                print("Loading ESM-2 650M (one-time cost per instance)...")
                _scorer = await asyncio.to_thread(ESM2Scorer)
                print(f"Model loaded on device: {_scorer.device}")
    return _scorer


class ScoreRequest(BaseModel):
    job_id: str
    sequence_hash: str
    model_id: str


@app.get("/health")
async def health() -> dict[str, str]:
    """Answers before the model is loaded — this is the startup probe."""
    return {"status": "ok", "model_loaded": str(_scorer is not None)}


@app.post("/score")
async def score(req: ScoreRequest) -> dict:
    """
    Run one scoring job synchronously. The caller (Cloud Tasks) holds the
    connection for the duration, which is what keeps CPU allocated.

    Errors propagate as 500 so Cloud Tasks retries; `run_scoring` has
    already marked the job ERROR in Postgres either way, so the frontend
    sees a terminal state rather than polling forever.
    """
    from worker.scorers.esm2 import DEFAULT_REVISION

    scorer = await get_scorer()
    return await run_scoring(
        scorer,
        job_id=req.job_id,
        sequence_hash=req.sequence_hash,
        model_id=req.model_id,
        model_revision=DEFAULT_REVISION,
    )
