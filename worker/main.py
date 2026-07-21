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

        except Exception as exc:  # noqa: BLE001
            await jobs.mark_error(job_id, error_message=repr(exc))
            raise

    # Best-effort structural features (DSSP). Runs after the job is already
    # marked done and in its own session, so a structure/DSSP hiccup can never
    # fail or delay the score the user is waiting on.
    try:
        await compute_and_store_structure_features(sequence_hash)
    except Exception as exc:  # noqa: BLE001
        print(f"[features] skipped for {sequence_hash}: {exc!r}")

    return {"sequence_hash": sequence_hash, "model_id": model_id, "uri": uri}


async def compute_and_store_structure_features(sequence_hash: str) -> None:
    """
    Fetch the protein's structure (AlphaFold or RCSB), run DSSP, and store the
    resulting StructureContext in UniProt coordinates. Idempotent and skipped
    for FASTA-only proteins that have no structure.
    """
    from api.services.structure_client import StructureClient
    from api.services.structure_service import StructureService
    from storage.structure_store import get_structure_store
    from worker.features.dssp import compute_structure_context

    async with async_session_factory() as session:
        client = StructureClient()
        try:
            structures = StructureService(session, get_structure_store(), client)
            if structures.load_features(sequence_hash) is not None:
                return  # already computed
            record = await structures.get_or_fetch(sequence_hash)
            if record is None:
                return  # FASTA-only / no structure available

            protein = await session.execute(
                select(Protein).where(Protein.sequence_hash == sequence_hash)
            )
            length = protein.scalar_one().length

            pdb_bytes = structures.store.read(record.structure_uri)
            segments = (
                await structures.load_sifts_segments(sequence_hash)
                if record.provider == "rcsb"
                else None
            )
            context = compute_structure_context(pdb_bytes, length, segments)
            structures.store_features(sequence_hash, context)
        finally:
            await client.aclose()


class WorkerSettings:
    functions = [score_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:6379")
    )
    max_jobs = 1
