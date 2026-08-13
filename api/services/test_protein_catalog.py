"""
Tests for the already-scored protein listing.

The privacy rule is the important one: a visitor may paste unpublished work,
and it must never end up advertised on the front page to everyone else.
"""

from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

import pytest

from api.services.protein_catalog import ProteinCatalog, reset_name_cache


class _Rows:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class _FakeSession:
    """Captures the statement so the test can assert on the filtering."""

    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.statements: list[Any] = []

    async def execute(self, statement):  # noqa: ANN001
        self.statements.append(statement)
        return _Rows(self.rows)


class _FakeUniProt:
    def __init__(self, names: dict[str, tuple[str, str]]) -> None:
        self.names = names
        self.calls = 0

    async def fetch_entry_names(self, accessions):  # noqa: ANN001
        self.calls += 1
        return {a: self.names[a] for a in accessions if a in self.names}


def as_session(fake: Any) -> AsyncSession:
    return cast(AsyncSession, fake)


@pytest.fixture(autouse=True)
def _clear_name_cache():
    """The name cache is module-level, so it leaks between tests."""
    reset_name_cache()
    yield
    reset_name_cache()


async def test_pasted_sequences_are_excluded_in_sql() -> None:
    """
    The exclusion has to be part of the query, not a filter applied afterwards,
    so there is no path where a FASTA entry is fetched and then forgotten about.
    """
    session = _FakeSession([("P04637", 393, "a" * 64)])
    catalog = ProteinCatalog(as_session(session), uniprot=None)
    await catalog.scored(model_id="esm2_t33_650M_UR50D")

    sql = str(session.statements[0]).lower()
    assert "uniprot_id is not null" in sql
    # And it must only count proteins that really are scored.
    assert "join score_matrices" in sql or "score_matrices" in sql


async def test_rows_without_an_accession_never_survive() -> None:
    """Belt and braces: even if such a row reached us, it is dropped."""
    session = _FakeSession(
        [("P04637", 393, "a" * 64), (None, 76, "b" * 64), ("", 50, "c" * 64)]
    )
    catalog = ProteinCatalog(as_session(session), uniprot=None)
    entries = await catalog.scored(model_id="esm2_t33_650M_UR50D")
    assert [e.uniprot_id for e in entries] == ["P04637"]


async def test_names_are_looked_up_once_and_reused() -> None:
    fake = _FakeUniProt({"P04637": ("TP53", "Cellular tumor antigen p53")})
    session = _FakeSession([("P04637", 393, "a" * 64)])
    catalog = ProteinCatalog(as_session(session), uniprot=cast(Any, fake))

    first = await catalog.scored(model_id="m")
    assert first[0].gene == "TP53"
    assert first[0].name == "Cellular tumor antigen p53"

    # Second call must hit the process cache rather than UniProt again.
    before = fake.calls
    await catalog.scored(model_id="m")
    assert fake.calls == before


async def test_falls_back_to_the_accession_when_names_are_unavailable() -> None:
    """A UniProt outage must not empty the list or break the page."""

    class _Broken:
        async def fetch_entry_names(self, accessions):  # noqa: ANN001
            raise RuntimeError("uniprot down")

    session = _FakeSession([("Q9NEW01", 200, "d" * 64)])
    catalog = ProteinCatalog(as_session(session), uniprot=cast(Any, _Broken()))
    entries = await catalog.scored(model_id="m")
    assert entries[0].gene == "Q9NEW01"  # accession stands in for the symbol
    assert entries[0].name == ""
