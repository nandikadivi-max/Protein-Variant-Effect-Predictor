"""
ARQ worker entrypoint — the *pull* transport, used in local development.

The ESM-2 model loads ONCE at startup into a module-level singleton and
stays warm across every job. This is the right shape on a laptop or any
always-on host: the model never reloads, so repeat scoring is fast.

In production the worker runs the *push* transport instead
(`worker/http_app.py`, driven by Cloud Tasks) so that it can scale to
zero when idle. Both share `worker/scoring_job.run_scoring`.
"""

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from arq.connections import RedisSettings

from worker.scorers.esm2 import DEFAULT_REVISION, ESM2Scorer
from worker.scoring_job import run_scoring

SCORER: ESM2Scorer | None = None


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args) -> None:  # silence per-request logging
        pass


def _start_health_server() -> None:
    """
    Serve a 200 on $PORT in a daemon thread. The ARQ worker consumes from Redis
    and never handles HTTP, but some platforms require a container to pass a
    startup probe on the injected port. Harmless off-platform.
    """
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Health server listening on :{port}")


async def startup(ctx: dict) -> None:
    global SCORER
    _start_health_server()
    print("Loading ESM-2 650M (one-time cost)...")
    SCORER = ESM2Scorer()
    print(f"Model loaded on device: {SCORER.device}")


async def shutdown(ctx: dict) -> None:
    pass


async def score_job(ctx: dict, *, job_id: str, sequence_hash: str, model_id: str) -> dict:
    """Score one protein with one model and persist the matrix."""
    assert SCORER is not None, "Worker startup did not run"
    return await run_scoring(
        SCORER,
        job_id=job_id,
        sequence_hash=sequence_hash,
        model_id=model_id,
        model_revision=DEFAULT_REVISION,
    )


class WorkerSettings:
    functions = [score_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:6379")
    )
    max_jobs = 1
