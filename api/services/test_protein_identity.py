"""
One protein, one record, whatever identifier was used to reach it.

The upsert is the interesting part: the row is keyed by sequence hash, so
every input format for a given protein collides on it, but only some formats
carry an accession. Getting the conflict rule wrong means the identity
depends on who searched first.
"""

from api.services.protein_resolver import ProteinResolver
from db.models import Protein


def _compile(stmt) -> str:
    from sqlalchemy.dialects import postgresql

    return str(stmt.compile(dialect=postgresql.dialect()))


class _CapturingSession:
    def __init__(self) -> None:
        self.statements: list = []

    async def execute(self, statement):  # noqa: ANN001
        self.statements.append(statement)

        class _R:
            @staticmethod
            def scalar_one_or_none():
                return None

        return _R()

    async def commit(self) -> None:
        pass


async def test_conflict_fills_in_a_missing_identity_but_never_replaces_one() -> None:
    from typing import Any, cast

    from sqlalchemy.ext.asyncio import AsyncSession
    from domain.resolve import build_resolved_protein

    session = _CapturingSession()
    resolver = ProteinResolver(
        session=cast(AsyncSession, cast(Any, session)), uniprot=cast(Any, None)
    )
    protein = build_resolved_protein(
        sequence="MKV",
        coordinate_system="uniprot",
        uniprot_id="P04637",
        structure_ref=None,
        source="uniprot:P04637",
    )
    await resolver._upsert_protein(protein)

    sql = _compile(session.statements[0]).lower()
    # It must update on conflict, not silently ignore the better information.
    assert "on conflict" in sql and "do update" in sql
    # ...but only when we are adding an identity, never overwriting one.
    assert "uniprot_id is null" in sql
    assert "is not null" in sql


def test_protein_row_is_keyed_only_by_sequence_hash() -> None:
    """
    Deduplication rests entirely on this: the primary key is the hash of the
    sequence, so a gene name, an accession, a PDB id and a pasted sequence
    that all denote the same protein land on one row and share one score.
    """
    pk = [c.name for c in Protein.__table__.primary_key.columns]
    assert pk == ["sequence_hash"]
