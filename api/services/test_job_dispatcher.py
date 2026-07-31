"""
Dispatcher selection tests. No network, no Redis, no GCP — these check the
config wiring, which is where a deploy actually goes wrong (a half-set env
var that silently queues into a void).
"""

import json
from dataclasses import dataclass

import pytest

from api.services.job_dispatcher import (
    ArqDispatcher,
    CloudTasksDispatcher,
    build_dispatcher,
)


@dataclass
class FakeSettings:
    job_dispatch: str = "arq"
    gcp_project: str | None = None
    cloud_tasks_location: str = "us-central1"
    cloud_tasks_queue: str | None = None
    cloud_tasks_service_account: str | None = None
    worker_url: str | None = None


CLOUDTASKS_OK = FakeSettings(
    job_dispatch="cloudtasks",
    gcp_project="proj",
    cloud_tasks_queue="pvep-jobs",
    cloud_tasks_service_account="sa@proj.iam.gserviceaccount.com",
    worker_url="https://worker.run.app",
)


class FakeArq:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def enqueue_job(self, function: str, *args, **kwargs) -> None:
        self.calls.append({"name": function, **kwargs})


async def test_arq_dispatcher_enqueues_score_job() -> None:
    arq = FakeArq()
    await ArqDispatcher(arq).dispatch(
        job_id="j1", sequence_hash="abc", model_id="esm2"
    )
    assert arq.calls == [
        {"name": "score_job", "job_id": "j1", "sequence_hash": "abc", "model_id": "esm2"}
    ]


def test_build_dispatcher_selects_arq() -> None:
    arq = FakeArq()
    assert isinstance(build_dispatcher(FakeSettings(), arq), ArqDispatcher)


def test_build_dispatcher_arq_without_pool_raises() -> None:
    with pytest.raises(RuntimeError, match="requires a Redis pool"):
        build_dispatcher(FakeSettings(), None)


def test_build_dispatcher_selects_cloudtasks() -> None:
    dispatcher = build_dispatcher(CLOUDTASKS_OK, None)
    assert isinstance(dispatcher, CloudTasksDispatcher)
    # Trailing slashes would produce a "//score" target URL.
    assert dispatcher.worker_url == "https://worker.run.app"


def test_cloudtasks_strips_trailing_slash() -> None:
    settings = FakeSettings(**{**CLOUDTASKS_OK.__dict__, "worker_url": "https://w.app/"})
    dispatcher = build_dispatcher(settings, None)
    assert isinstance(dispatcher, CloudTasksDispatcher)
    assert dispatcher.worker_url == "https://w.app"


@pytest.mark.parametrize(
    "missing_field,expected",
    [
        ("gcp_project", "GCP_PROJECT"),
        ("cloud_tasks_queue", "CLOUD_TASKS_QUEUE"),
        ("worker_url", "WORKER_URL"),
        ("cloud_tasks_service_account", "CLOUD_TASKS_SERVICE_ACCOUNT"),
    ],
)
def test_cloudtasks_names_the_missing_env_var(missing_field: str, expected: str) -> None:
    settings = FakeSettings(**{**CLOUDTASKS_OK.__dict__, missing_field: None})
    with pytest.raises(RuntimeError, match=expected):
        build_dispatcher(settings, None)


def test_unknown_backend_raises() -> None:
    with pytest.raises(RuntimeError, match="Unknown JOB_DISPATCH"):
        build_dispatcher(FakeSettings(job_dispatch="rabbitmq"), None)


async def test_cloudtasks_builds_a_well_formed_task() -> None:
    """The task body is what the worker's POST /score parses, so pin its shape."""
    tasks_v2 = pytest.importorskip("google.cloud.tasks_v2")

    captured: dict = {}

    class FakeClient:
        def queue_path(self, project, location, queue):
            return f"projects/{project}/locations/{location}/queues/{queue}"

        async def create_task(self, parent, task):
            captured["parent"] = parent
            captured["task"] = task

    dispatcher = build_dispatcher(CLOUDTASKS_OK, None)
    assert isinstance(dispatcher, CloudTasksDispatcher)
    dispatcher._client = FakeClient()

    await dispatcher.dispatch(job_id="j1", sequence_hash="abc", model_id="esm2")

    assert captured["parent"] == "projects/proj/locations/us-central1/queues/pvep-jobs"
    req = captured["task"]["http_request"]
    assert req["url"] == "https://worker.run.app/score"
    assert req["http_method"] == tasks_v2.HttpMethod.POST
    assert json.loads(req["body"]) == {
        "job_id": "j1",
        "sequence_hash": "abc",
        "model_id": "esm2",
    }
    # Audience must be the service root, not the /score path, or Cloud Run
    # rejects the OIDC token.
    assert req["oidc_token"]["audience"] == "https://worker.run.app"
