"""
ARQ worker entrypoint. The ESM-2 model loads ONCE at startup into a
module-level singleton and stays warm across every job — this is what
makes single-mutation queries fast after the first protein scan.

The job function:
  1. loads the sequence from Postgres by sequence_hash
  2. runs the scorer to produce the (L, 20) matrix
  3. writes the matrix to object storage via MatrixStore
  4. records the (sequence_hash, model_id) -> matrix_uri row in
     score_matrices
  5. marks the job DONE
"""

import os

from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from api.services.job_service import JobService
from db.models import Protein, ScoreMatrix
from db.session import async_session_factory
from storage.matrix_store import get_matrix_store
from worker.scorers.esm2 import DEFAULT_REVISION, ESM2Scorer

SCORER: ESM2Scorer | None = None


async def startup(ctx: dict) -> None:
    global SCORER
    print("Loading ESM-2 650M (one-time cost)...")
    SCORER = ESM2Scorer()
    print(f"Model loaded on device: {SCORER.device}")


async def shutdown(ctx: dict) -> None:
    pass


async def score_job(ctx: dict, *, job_id: str, sequence_hash: str, model_id: str) -> dict:
    """
    Score one protein with one model and persist the matrix. This is the
    only job type in v1.
    """
    assert SCORER is not None, "Worker startup did not run"

    async with async_session_factory() as session:
        jobs = JobService(session=session, arq=ctx["redis"])
        await jobs.mark_running(job_id)

        try:
            # Fetch the sequence.
            result = await session.execute(
                select(Protein).where(Protein.sequence_hash == sequence_hash)
            )
            protein = result.scalar_one_or_none()
            if protein is None:
                raise RuntimeError(f"Protein {sequence_hash} not in database")

            # Score it. This is the expensive step.
            matrix = SCORER.per_position_log_probs(protein.sequence)

            # Persist matrix bytes, then the DB pointer.
            store = get_matrix_store()
            uri = store.write(model_id, sequence_hash, matrix)

            stmt = (
                pg_insert(ScoreMatrix)
                .values(
                    sequence_hash=sequence_hash,
                    model_id=model_id,
                    matrix_uri=uri,
                    model_revision=DEFAULT_REVISION,
                )
                .on_conflict_do_nothing(index_elements=["sequence_hash", "model_id"])
            )
            await session.execute(stmt)
            await session.commit()

            await jobs.mark_done(job_id)
            return {"sequence_hash": sequence_hash, "model_id": model_id, "uri": uri}

        except Exception as exc:  # noqa: BLE001
            await jobs.mark_error(job_id, error_message=repr(exc))
            raise


class WorkerSettings:
    functions = [score_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:6379")
    )
    max_jobs = 1
