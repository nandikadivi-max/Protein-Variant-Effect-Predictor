"""
Job orchestration. This is the piece that decides whether a new (protein,
model) request actually needs to be computed, or is a cache hit that
should short-circuit past the queue entirely.

The cache-hit path is critical: any repeat request for a protein we've
already scored returns instantly, without touching the worker. This is
what makes the whole system tolerable on CPU.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.job_dispatcher import JobDispatcher
from config import get_settings
from contracts.schemas import JobStatus
from db.models import Job, Protein, ScoreMatrix


class UnknownProtein(Exception):
    """No protein row for this sequence_hash. Resolve it first."""


class UnsupportedModel(Exception):
    """A model this deployment does not serve."""


class DailyLimitReached(Exception):
    """
    The rolling-24h budget for scoring novel proteins is spent.

    Only ever raised for work that would actually wake the worker. Cache hits
    do not consume the budget and are not refused.
    """


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

        # Only now, once we know this needs real work, does the cost guard
        # apply. Placing it after the cache check is the whole point: a cache
        # hit costs nothing and must never be refused.
        await self._assert_daily_budget()

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

    # A real scoring run is never this quick. The smallest demo protein is 46
    # residues at roughly a second each, before a cold start adds a minute or
    # so on top. A cache-hit row, by contrast, is written already finished
    # inside a single transaction.
    #
    # The generous margin is deliberate. `created_at` comes from the database
    # clock and `finished_at` from the API process's, so the difference on a
    # cache hit is near zero but not exactly zero, and could even be slightly
    # negative. Thirty seconds is far outside any plausible skew between two
    # NTP-synced hosts while still sitting well below the shortest genuine run.
    _MIN_REAL_JOB_SECONDS = 30

    async def _assert_daily_budget(self) -> None:
        """
        Refuse to start new scoring once the rolling 24-hour allowance is gone.

        Scoring is the only expensive thing here and the API has to be public,
        so without this an unattended deployment has no upper bound on spend.

        Counts genuine runs only. The cache-hit path above also writes a Job
        row — that table doubles as the request log — so the two are told apart
        by how long the row took to finish rather than by a dedicated column,
        which would mean a migration for something this small. A run that fails
        within the window is not counted, which is the right bias: it barely
        cost anything.
        """
        limit = get_settings().max_new_jobs_per_day
        # Negative disables the guard. Zero deliberately does NOT: it means
        # "score nothing new", which is the emergency brake. Reaching for 0 to
        # stop spending and getting unlimited scoring instead is exactly the
        # wrong way round for a setting whose whole purpose is a cost ceiling.
        if limit < 0:
            return

        window_start = datetime.now(timezone.utc) - timedelta(hours=24)
        floor = timedelta(seconds=self._MIN_REAL_JOB_SECONDS)
        used = await self.session.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.created_at >= window_start,
                or_(
                    Job.finished_at.is_(None),
                    Job.finished_at > Job.created_at + floor,
                ),
            )
        )
        if (used or 0) >= limit:
            if limit == 0:
                raise DailyLimitReached(
                    "New proteins aren't being scored at the moment. "
                    "Everything already scored still works and is instant, so "
                    "the examples and the catalogue below them are all live."
                )
            raise DailyLimitReached(
                f"This demo scores up to {limit} new proteins a day, and "
                "today's allowance is used up. Everything already scored is "
                "unaffected and still instant, including the examples. New "
                "proteins can be scored again within 24 hours."
            )

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
