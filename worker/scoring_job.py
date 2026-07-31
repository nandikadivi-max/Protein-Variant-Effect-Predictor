"""
The actual work of a scoring job, independent of how the job arrived.

Both worker entrypoints — `worker/main.py` (ARQ, pulls from Redis) and
`worker/http_app.py` (HTTP, pushed to by Cloud Tasks) — are thin wrappers
around `run_scoring`. Keeping the body here means the two transports can
never drift in what they actually compute or persist.

Note this module does not import torch: it takes an already-constructed
`Scorer` (the warm singleton owned by whichever entrypoint is running).
"""

import asyncio

from sqlalchemy import select

from api.services.job_service import JobService
from db.models import Protein, ScoreMatrix
from db.session import async_session_factory
from domain.scoring import Scorer
from storage.matrix_store import get_matrix_store


async def run_scoring(
    scorer: Scorer,
    *,
    job_id: str,
    sequence_hash: str,
    model_id: str,
    model_revision: str | None = None,
) -> dict:
    """
    Load the sequence, score it, persist the matrix + DB pointer, mark the
    job done. Raises after marking the job ERROR so the transport can retry.

    Deliberately uses three short-lived sessions rather than one long one.
    Scoring a long protein takes minutes, and a managed Postgres (Neon and
    friends are serverless and aggressive about idle connections) will drop a
    connection held open across it — the write afterwards then fails with
    PendingRollbackError and the job dies *after* the expensive work is done.
    No connection is held while the model runs.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    try:
        # --- Session 1: claim the job and read the sequence. Short. ---
        async with async_session_factory() as session:
            await JobService(session=session).mark_running(job_id)
            result = await session.execute(
                select(Protein).where(Protein.sequence_hash == sequence_hash)
            )
            protein = result.scalar_one_or_none()
            if protein is None:
                raise RuntimeError(f"Protein {sequence_hash} not in database")
            sequence = protein.sequence

        # --- No DB connection held here. ---
        #
        # The expensive step; everything else in the system is a cheap
        # derivation of this one (L, 20) matrix.
        #
        # Off the event loop: this is seconds-to-minutes of blocking CPU, and
        # the HTTP transport must keep answering /health throughout or Cloud
        # Run will judge the container unresponsive and kill the job.
        matrix = await asyncio.to_thread(scorer.per_position_log_probs, sequence)

        store = get_matrix_store()
        uri = store.write(model_id, sequence_hash, matrix)

        # --- Session 2: record the matrix and finish the job. Short. ---
        async with async_session_factory() as session:
            stmt = (
                pg_insert(ScoreMatrix)
                .values(
                    sequence_hash=sequence_hash,
                    model_id=model_id,
                    matrix_uri=uri,
                    model_revision=model_revision,
                )
                .on_conflict_do_nothing(index_elements=["sequence_hash", "model_id"])
            )
            await session.execute(stmt)
            await session.commit()
            await JobService(session=session).mark_done(job_id)

    except Exception as exc:  # noqa: BLE001
        # --- Session 3: a fresh connection, because the failure above may well
        # BE a dead connection. Reusing the broken session would lose the error.
        try:
            async with async_session_factory() as session:
                await JobService(session=session).mark_error(
                    job_id, error_message=repr(exc)
                )
        except Exception as mark_exc:  # noqa: BLE001
            print(f"[job {job_id}] could not record failure: {mark_exc!r}")
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
