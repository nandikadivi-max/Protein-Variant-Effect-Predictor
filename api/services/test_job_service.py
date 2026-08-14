"""
Input-validation tests for JobService.

These cover the two ways a malformed job request used to get through, both
of which cost real money rather than merely returning an ugly response.
"""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.job_service import (
    DailyLimitReached,
    JobService,
    UnknownProtein,
    UnsupportedModel,
)
from api.services.uniprot_client import _echo_safe
from config import get_settings
from contracts.schemas import JobStatus


def as_session(fake: Any) -> AsyncSession:
    """The fakes below implement only the handful of methods these paths use."""
    return cast(AsyncSession, fake)


class _NeverCalledSession:
    """Fails loudly if validation lets anything reach the database."""

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("validation should have rejected this first")


class _NoProteinSession:
    """A session whose protein lookup always comes back empty."""

    def __init__(self) -> None:
        self.added: list = []

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        class _Result:
            @staticmethod
            def scalar_one_or_none():
                return None

        return _Result()

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        pass


class _RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list = []

    async def dispatch(self, **kwargs) -> None:  # noqa: ANN003
        self.calls.append(kwargs)


async def test_unknown_model_is_rejected_before_any_db_work() -> None:
    """
    An unrecognised model can never match a cached matrix, so it used to
    create a job and wake the worker for a full scoring run every single
    time, then store the result under a model that doesn't exist.
    """
    service = JobService(
        session=as_session(_NeverCalledSession()),
        dispatcher=_RecordingDispatcher(),
    )
    with pytest.raises(UnsupportedModel, match="Unknown model"):
        await service.create_or_reuse(sequence_hash="a" * 64, model_id="not-a-model")


async def test_unknown_protein_is_rejected_and_nothing_is_dispatched() -> None:
    """Previously a foreign-key violation surfacing as a 500."""
    dispatcher = _RecordingDispatcher()
    service = JobService(session=as_session(_NoProteinSession()), dispatcher=dispatcher)
    with pytest.raises(UnknownProtein, match="Resolve the protein first"):
        await service.create_or_reuse(
            sequence_hash="0" * 64, model_id="esm2_t33_650M_UR50D"
        )
    assert dispatcher.calls == []


class _ScriptedSession:
    """Protein always exists; cache state and the 24h count are configurable."""

    def __init__(self, *, cached: bool, jobs_today: int) -> None:
        self.cached = cached
        self.jobs_today = jobs_today
        self.added: list = []
        self._executes = 0

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self._executes += 1
        is_protein_lookup = self._executes == 1
        cached = self.cached

        class _Result:
            @staticmethod
            def scalar_one_or_none():
                if is_protein_lookup:
                    return "a" * 64  # the protein row exists
                return object() if cached else None  # the score matrix

        return _Result()

    async def scalar(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self.jobs_today

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        pass


def _with_limit(monkeypatch: pytest.MonkeyPatch, limit: int) -> None:
    model_id = get_settings().default_model_id
    monkeypatch.setattr(
        "api.services.job_service.get_settings",
        lambda: SimpleNamespace(
            default_model_id=model_id, max_new_jobs_per_day=limit
        ),
    )


async def test_new_scoring_is_refused_once_the_daily_budget_is_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Scoring is the only expensive thing here and the API is public, so without
    a ceiling an unattended deployment has no upper bound on spend.
    """
    _with_limit(monkeypatch, 5)
    dispatcher = _RecordingDispatcher()
    service = JobService(
        session=as_session(_ScriptedSession(cached=False, jobs_today=5)),
        dispatcher=dispatcher,
    )
    with pytest.raises(DailyLimitReached, match="5 new proteins a day"):
        await service.create_or_reuse(
            sequence_hash="a" * 64, model_id=get_settings().default_model_id
        )
    # The point of the guard is that the worker is never woken.
    assert dispatcher.calls == []


async def test_cached_proteins_are_served_even_with_the_budget_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The guard must never touch the cache-hit path. A cache hit costs nothing,
    and refusing one would take the demo examples down precisely when someone
    is looking at them.
    """
    _with_limit(monkeypatch, 5)
    service = JobService(
        session=as_session(_ScriptedSession(cached=True, jobs_today=500)),
        dispatcher=_RecordingDispatcher(),
    )
    _job_id, status, cached = await service.create_or_reuse(
        sequence_hash="a" * 64, model_id=get_settings().default_model_id
    )
    assert cached is True
    assert status is JobStatus.DONE


async def test_budget_below_the_limit_dispatches_normally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_limit(monkeypatch, 5)
    dispatcher = _RecordingDispatcher()
    service = JobService(
        session=as_session(_ScriptedSession(cached=False, jobs_today=4)),
        dispatcher=dispatcher,
    )
    _job_id, status, cached = await service.create_or_reuse(
        sequence_hash="a" * 64, model_id=get_settings().default_model_id
    )
    assert (cached, status) == (False, JobStatus.QUEUED)
    assert len(dispatcher.calls) == 1


async def test_zero_is_the_emergency_brake_not_unlimited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Zero must mean "score nothing new", never "no ceiling".

    Anyone setting this in a hurry is trying to stop spending. If the
    intuitive value quietly removed the cap instead, the one lever meant to
    halt costs would be the lever that uncaps them.
    """
    _with_limit(monkeypatch, 0)
    dispatcher = _RecordingDispatcher()
    service = JobService(
        session=as_session(_ScriptedSession(cached=False, jobs_today=0)),
        dispatcher=dispatcher,
    )
    with pytest.raises(DailyLimitReached, match="aren't being scored"):
        await service.create_or_reuse(
            sequence_hash="a" * 64, model_id=get_settings().default_model_id
        )
    assert dispatcher.calls == []


async def test_zero_still_serves_everything_already_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The brake must stop spending without taking the site down."""
    _with_limit(monkeypatch, 0)
    service = JobService(
        session=as_session(_ScriptedSession(cached=True, jobs_today=0)),
        dispatcher=_RecordingDispatcher(),
    )
    _job_id, status, cached = await service.create_or_reuse(
        sequence_hash="a" * 64, model_id=get_settings().default_model_id
    )
    assert (cached, status) == (True, JobStatus.DONE)


async def test_a_negative_limit_disables_the_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Escape hatch for local development."""
    _with_limit(monkeypatch, -1)
    dispatcher = _RecordingDispatcher()
    service = JobService(
        session=as_session(_ScriptedSession(cached=False, jobs_today=10_000)),
        dispatcher=dispatcher,
    )
    await service.create_or_reuse(
        sequence_hash="a" * 64, model_id=get_settings().default_model_id
    )
    assert len(dispatcher.calls) == 1


def test_echo_safe_strips_control_characters_and_truncates() -> None:
    """Error strings go to the log as well as the client, so a newline in the
    input must not be able to forge a second log line."""
    assert "\n" not in _echo_safe("TP53\nP04637")
    assert _echo_safe("TP53\nP04637") == "TP53P04637"
    assert _echo_safe("\r\n\t") == ""
    long = _echo_safe("A" * 500)
    assert len(long) <= 61 and long.endswith("…")
    # Ordinary input is untouched.
    assert _echo_safe("TP53") == "TP53"
