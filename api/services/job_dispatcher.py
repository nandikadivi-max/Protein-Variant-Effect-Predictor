"""
How a queued job reaches the worker. This is the one place that knows,
and the API depends only on the protocol below — `JobService` calls
`dispatch()` and never learns which transport carried the job.

Two transports exist because dev and production want opposite things:

- `ArqDispatcher` (dev): the worker is a long-lived process that *pulls*
  from Redis. The model loads once and stays warm forever, which is what
  you want on a laptop where you re-run the same protein all day.

- `CloudTasksDispatcher` (prod): the worker is a Cloud Run service that
  is *pushed* to over HTTP. Cloud Run allocates CPU for the life of the
  request and scales back to zero afterwards, so an idle deployment costs
  nothing. A pull-based worker cannot scale to zero — there is no request
  to scale on — and would have to run 24/7 at full price.

The warm-singleton design survives both: the worker holds the model for
the lifetime of its process either way. Under Cloud Tasks that lifetime
is "until Cloud Run reaps the instance" rather than "forever", so the
first job after an idle period pays the model load. Repeat requests for
an already-scored protein never reach here at all — `JobService` short-
circuits on the matrix cache before dispatching.
"""

import json
from typing import Any, Protocol


class JobDispatcher(Protocol):
    """Hand a scoring job to the worker. Implementations must be idempotent-safe
    to call once per created job row; they do not wait for the job to finish."""

    async def dispatch(self, *, job_id: str, sequence_hash: str, model_id: str) -> None: ...


class Enqueuer(Protocol):
    """The single method `ArqDispatcher` needs from an `ArqRedis` pool.
    Depending on the capability rather than the concrete client keeps this
    module import-light and makes the dispatcher trivially fakeable."""

    # Mirrors arq.ArqRedis.enqueue_job so the real pool satisfies this
    # structurally, with no adapter and no import of arq here.
    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> Any: ...


class ArqDispatcher:
    """Enqueue onto Redis for a long-running ARQ worker to pull."""

    def __init__(self, arq: Enqueuer) -> None:
        self.arq = arq

    async def dispatch(self, *, job_id: str, sequence_hash: str, model_id: str) -> None:
        await self.arq.enqueue_job(
            "score_job",
            job_id=job_id,
            sequence_hash=sequence_hash,
            model_id=model_id,
        )


class CloudTasksDispatcher:
    """
    Create a Cloud Tasks HTTP task targeting the worker's `POST /score`.

    Cloud Tasks — not a direct POST from this process — because the API is
    itself a scale-to-zero Cloud Run service: it must return the job_id in
    milliseconds while the scoring request runs for ~60s. A background task
    here would be CPU-throttled the moment the response is sent, and the
    instance can be reclaimed mid-flight. Cloud Tasks owns the long request,
    retries on 5xx, and is free under 1M dispatches/month.
    """

    def __init__(
        self,
        *,
        project: str,
        location: str,
        queue: str,
        worker_url: str,
        service_account_email: str,
        deadline_seconds: int = 1800,
    ) -> None:
        self.project = project
        self.location = location
        self.queue = queue
        self.worker_url = worker_url.rstrip("/")
        self.service_account_email = service_account_email
        self.deadline_seconds = deadline_seconds
        self._client: Any = None

    def _get_client(self):
        # Imported lazily so local dev (and the test suite) need not install
        # google-cloud-tasks at all — see the [gcp] extra in pyproject.toml.
        if self._client is None:
            from google.cloud import tasks_v2

            self._client = tasks_v2.CloudTasksAsyncClient()
        return self._client

    async def dispatch(self, *, job_id: str, sequence_hash: str, model_id: str) -> None:
        from google.cloud import tasks_v2

        client = self._get_client()
        payload = {
            "job_id": job_id,
            "sequence_hash": sequence_hash,
            "model_id": model_id,
        }
        await client.create_task(
            parent=client.queue_path(self.project, self.location, self.queue),
            task={
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": f"{self.worker_url}/score",
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(payload).encode(),
                    # The worker is deployed --no-allow-unauthenticated; Cloud
                    # Run verifies this token at ingress, so the worker itself
                    # needs no auth code.
                    "oidc_token": {
                        "service_account_email": self.service_account_email,
                        "audience": self.worker_url,
                    },
                },
                # Scoring a long protein on CPU plus a cold model load can take
                # minutes. Default deadline is 10min; 30min is the HTTP-target max.
                "dispatch_deadline": {"seconds": self.deadline_seconds},
            },
        )


def build_dispatcher(settings: Any, arq: Enqueuer | None = None) -> JobDispatcher:
    """Select the transport from config. Fails loudly on a half-configured
    cloudtasks setup rather than silently falling back to a queue nothing reads."""
    backend = settings.job_dispatch.lower()

    if backend == "arq":
        if arq is None:
            raise RuntimeError("JOB_DISPATCH=arq requires a Redis pool")
        return ArqDispatcher(arq)

    if backend == "cloudtasks":
        missing = [
            name
            for name, value in (
                ("GCP_PROJECT", settings.gcp_project),
                ("CLOUD_TASKS_QUEUE", settings.cloud_tasks_queue),
                ("WORKER_URL", settings.worker_url),
                ("CLOUD_TASKS_SERVICE_ACCOUNT", settings.cloud_tasks_service_account),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                f"JOB_DISPATCH=cloudtasks requires: {', '.join(missing)}"
            )
        return CloudTasksDispatcher(
            project=settings.gcp_project,
            location=settings.cloud_tasks_location,
            queue=settings.cloud_tasks_queue,
            worker_url=settings.worker_url,
            service_account_email=settings.cloud_tasks_service_account,
        )

    raise RuntimeError(f"Unknown JOB_DISPATCH backend: {settings.job_dispatch!r}")
