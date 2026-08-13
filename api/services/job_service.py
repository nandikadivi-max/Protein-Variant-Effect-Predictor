"""
Job orchestration. This is the piece that decides whether a new (protein,
model) request actually needs to be computed, or is a cache hit that
should short-circuit past the queue entirely.

The cache-hit path is critical: any repeat request for a protein we've
already scored returns instantly, without touching the worker. This is
what makes the whole system tolerable on CPU.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.job_dispatcher import JobDispatcher
from config import get_settings
from contracts.schemas import JobStatus
from db.models import Job, Protein, ScoreMatrix


class UnknownProtein(Exception):
    """No protein row for this sequence_hash. Resolve it first."""


class UnsupportedModel(Exception):
    """A model this deployment does not serve."""


class JobService:
    def __init__(
        self, session: AsyncSession, dispatcher: JobDispatcher | None = None
    ) -> None:
        self.session = session
        # Optional because the worker constructs a JobService purely to move
        # jobs through mark_running/mark_done/mark_error — it never dispatches.
        self.dispatcher = dispatcher

    async def create_or_reuse(
        self, sequence_hash: str, model_id: str
    ) -> tuple[str, JobStatus, bool]:
        """
        Returns (job_id, status, cached).
        - cached=True: the matrix already exists; job_id refers to a
          synthetic completed job, status is DONE, no work is enqueued.
        - cached=False: a new job is created and enqueued.

        Both inputs are validated before anything is written, because getting
        this wrong is expensive rather than merely untidy. An unrecognised
        model_id used to sail through: it could never match a cached matrix,
        so every request with a junk model name created a job and woke the
        worker for a full scoring run, then stored the result under a model
        that does not exist. An unknown sequence_hash used to violate the
        proteins foreign key and surface as a 500.
        """
        expected_model = get_settings().default_model_id
        if model_id != expected_model:
            raise UnsupportedModel(
                f"Unknown model '{model_id}'. This deployment serves {expected_model}."
            )

        protein = await self.session.execute(
            select(Protein.sequence_hash).where(
                Protein.sequence_hash == sequence_hash
            )
        )
        if protein.scalar_one_or_none() is None:
            raise UnknownProtein(
                f"No protein for sequence_hash '{sequence_hash[:16]}'. "
                "Resolve the protein first."
            )

        # Cache check — this is the whole point of the design.
        result = await self.session.execute(
            select(ScoreMatrix).where(
                ScoreMatrix.sequence_hash == sequence_hash,
                ScoreMatrix.model_id == model_id,
            )
        )
        if result.scalar_one_or_none() is not None:
            # Return a completed job record so the API surface is uniform.
            job_id = str(uuid.uuid4())
            job = Job(
                job_id=job_id,
                sequence_hash=sequence_hash,
                model_id=model_id,
                status=JobStatus.DONE.value,
                finished_at=datetime.now(timezone.utc),
            )
            self.session.add(job)
            await self.session.commit()
            return job_id, JobStatus.DONE, True

        # New job — persist, then enqueue.
        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            sequence_hash=sequence_hash,
            model_id=model_id,
            status=JobStatus.QUEUED.value,
        )
        self.session.add(job)
        await self.session.commit()

        if self.dispatcher is None:
            raise RuntimeError("JobService needs a dispatcher to enqueue work")
        await self.dispatcher.dispatch(
            job_id=job_id,
            sequence_hash=sequence_hash,
            model_id=model_id,
        )
        return job_id, JobStatus.QUEUED, False

    async def get_status(self, job_id: str) -> tuple[JobStatus, str | None] | None:
        result = await self.session.execute(select(Job).where(Job.job_id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return None
        return JobStatus(job.status), job.error

    async def mark_running(self, job_id: str) -> None:
        result = await self.session.execute(select(Job).where(Job.job_id == job_id))
        job = result.scalar_one()
        job.status = JobStatus.RUNNING.value
        await self.session.commit()

    async def mark_done(self, job_id: str) -> None:
        result = await self.session.execute(select(Job).where(Job.job_id == job_id))
        job = result.scalar_one()
        job.status = JobStatus.DONE.value
        job.finished_at = datetime.now(timezone.utc)
        await self.session.commit()

    async def mark_error(self, job_id: str, error_message: str) -> None:
        result = await self.session.execute(select(Job).where(Job.job_id == job_id))
        job = result.scalar_one()
        job.status = JobStatus.ERROR.value
        job.error = error_message
        job.finished_at = datetime.now(timezone.utc)
        await self.session.commit()
