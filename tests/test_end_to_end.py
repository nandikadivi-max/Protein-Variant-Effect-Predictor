"""
End-to-end integration test. Spins up nothing itself — assumes:

    docker compose up -d postgres redis

is running, and runs the FULL pipeline in-process:

    resolve -> create job -> score in-process (skipping ARQ worker for speed) -> read result

Run with:
    pytest tests/test_end_to_end.py -v -m "integration and network"

This test is IN PROCESS to make it fast and debuggable. There's a
separate contract that "the ARQ worker calls score_job with the same
arguments" — as long as JobService.create_or_reuse and worker.main.score_job
agree on the argument shape, the in-process test is faithful.

We use a small protein (ubiquitin, ~76 residues) to keep this test to a
few seconds even on CPU. TP53 (~393 residues) would take too long.
"""

import asyncio
import contextlib

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.network]

# Skip early if torch or a database driver isn't installed on this machine.
torch = pytest.importorskip("torch", reason="requires worker extras")
asyncpg = pytest.importorskip("asyncpg", reason="requires api/dev extras")

from sqlalchemy import select

from api.services.job_service import JobService
from api.services.protein_resolver import ProteinResolver
from api.services.results_service import ResultsService
from api.services.uniprot_client import UniProtClient
from contracts.schemas import JobStatus
from db.models import Protein, ScoreMatrix
from db.session import async_session_factory
from storage.matrix_store import get_matrix_store
from worker.scorers.esm2 import DEFAULT_REVISION, ESM2Scorer


# Ubiquitin, human, UniProt P0CG48, canonical is 685 aa (polyubiquitin).
# We use the single-repeat 76-residue mature ubiquitin instead by hitting
# UniProt P62988 (ubiquitin/CEP52), but simpler: paste the sequence in
# directly as raw FASTA to avoid any UniProt-canonical ambiguity.
UBIQUITIN_FASTA = (
    "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"
)


@pytest.fixture(scope="module")
def scorer() -> ESM2Scorer:
    return ESM2Scorer()


@pytest.mark.asyncio
async def test_end_to_end_ubiquitin(scorer):
    async with async_session_factory() as session:
        # 1. Resolve the protein via FASTA input.
        uniprot = UniProtClient()
        try:
            resolver = ProteinResolver(session=session, uniprot=uniprot)
            protein = await resolver.resolve(UBIQUITIN_FASTA)
        finally:
            await uniprot.aclose()

        assert protein.sequence == UBIQUITIN_FASTA
        assert protein.coordinate_system == "fasta"

        # 2. Compute + persist the matrix in-process (skipping the ARQ
        #    worker mechanic — see module docstring for why).
        matrix = scorer.per_position_log_probs(protein.sequence)
        store = get_matrix_store()
        uri = store.write(scorer.model_id, protein.sequence_hash, matrix)

        # Record the row that the worker would have written.
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = (
            pg_insert(ScoreMatrix)
            .values(
                sequence_hash=protein.sequence_hash,
                model_id=scorer.model_id,
                matrix_uri=uri,
                model_revision=DEFAULT_REVISION,
            )
            .on_conflict_do_nothing(index_elements=["sequence_hash", "model_id"])
        )
        await session.execute(stmt)
        await session.commit()

        # 3. Read a result for a specific mutation. L8P (leucine to
        #    proline at a helix-adjacent position in ubiquitin) is a
        #    known destabilizing substitution — should score negative.
        results_service = ResultsService(session=session, matrix_store=store)
        result = await results_service.build_result(
            sequence_hash=protein.sequence_hash,
            model_id=scorer.model_id,
            mutation="L8P",
        )

        assert result is not None
        assert result.length == len(UBIQUITIN_FASTA)
        assert len(result.effect_map) == len(UBIQUITIN_FASTA)
        assert len(result.effect_map[0]) == 20
        assert result.single is not None
        assert result.single.mutation == "L8P"
        # Not asserting sign here — this is an in-vitro test of the
        # pipeline, not a scoring correctness test. The correctness
        # check lives in worker/scorers/test_esm2_smoke.py (TP53 R175H).
        print(f"\nL8P LLR = {result.single.llr:.4f}, label = {result.single.label}")


@pytest.mark.asyncio
async def test_repeat_request_is_cache_hit(scorer):
    """Second request for the same (protein, model) must skip the queue."""
    async with async_session_factory() as session:
        # Make sure the protein + matrix exist first (relies on the previous
        # test having run, or does the work here idempotently).
        uniprot = UniProtClient()
        try:
            resolver = ProteinResolver(session=session, uniprot=uniprot)
            protein = await resolver.resolve(UBIQUITIN_FASTA)
        finally:
            await uniprot.aclose()

        # Ensure a matrix row exists (harmless if it's already there).
        result = await session.execute(
            select(ScoreMatrix).where(
                ScoreMatrix.sequence_hash == protein.sequence_hash,
                ScoreMatrix.model_id == scorer.model_id,
            )
        )
        if result.scalar_one_or_none() is None:
            matrix = scorer.per_position_log_probs(protein.sequence)
            store = get_matrix_store()
            uri = store.write(scorer.model_id, protein.sequence_hash, matrix)

            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = pg_insert(ScoreMatrix).values(
                sequence_hash=protein.sequence_hash,
                model_id=scorer.model_id,
                matrix_uri=uri,
                model_revision=DEFAULT_REVISION,
            ).on_conflict_do_nothing(index_elements=["sequence_hash", "model_id"])
            await session.execute(stmt)
            await session.commit()

        # Now the actual cache-hit check.
        class _FakeArq:
            enqueued = []
            async def enqueue_job(self, *args, **kwargs):
                self.enqueued.append((args, kwargs))

        fake_arq = _FakeArq()
        jobs = JobService(session=session, arq=fake_arq)
        job_id, status, cached = await jobs.create_or_reuse(
            sequence_hash=protein.sequence_hash, model_id=scorer.model_id
        )

        assert cached is True
        assert status == JobStatus.DONE
        assert fake_arq.enqueued == []  # no work was queued
