"""
Input-validation tests for JobService.

These cover the two ways a malformed job request used to get through, both
of which cost real money rather than merely returning an ugly response.
"""

from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.job_service import JobService, UnknownProtein, UnsupportedModel
from api.services.uniprot_client import _echo_safe


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
