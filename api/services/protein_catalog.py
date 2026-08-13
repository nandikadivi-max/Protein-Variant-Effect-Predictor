"""
The list of proteins already scored, offered back to visitors as instant picks.

The cache grows on its own: anything anyone scores is kept forever, keyed by
sequence hash, so the set of proteins that answer instantly widens with use.
This service is what makes that visible instead of invisible.

Two rules govern what may appear.

Pasted sequences are never listed. A visitor may paste unpublished work, and
surfacing it on the front page for everyone else would be a genuine privacy
failure — the fact that it is technically in our database is not permission to
advertise it. Only entries backed by a public identifier are eligible.

Only proteins that are genuinely scored are listed. Every entry offered here
must be a cache hit, or the promise of "instant" is false and clicking one
wakes the worker for minutes.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.uniprot_client import UniProtClient
from db.models import Protein, ScoreMatrix

# accession -> (gene symbol, protein name). Process-lifetime cache: these names
# never change, and the list is small and repeatedly requested.
_NAME_CACHE: dict[str, tuple[str, str]] = {}


def reset_name_cache() -> None:
    """Test hook: the cache is process-wide and would otherwise leak between tests."""
    _NAME_CACHE.clear()


@dataclass(frozen=True)
class CatalogEntry:
    uniprot_id: str
    gene: str
    name: str
    length: int
    sequence_hash: str


class ProteinCatalog:
    def __init__(self, session: AsyncSession, uniprot: UniProtClient | None = None):
        self.session = session
        self.uniprot = uniprot

    async def scored(self, model_id: str, limit: int = 12) -> list[CatalogEntry]:
        """Recently scored, publicly identifiable proteins, newest first."""
        rows = await self.session.execute(
            select(Protein.uniprot_id, Protein.length, Protein.sequence_hash)
            .join(ScoreMatrix, ScoreMatrix.sequence_hash == Protein.sequence_hash)
            .where(
                ScoreMatrix.model_id == model_id,
                # The privacy rule, enforced in SQL rather than after the fact:
                # a pasted sequence has no accession and can never be selected.
                Protein.uniprot_id.is_not(None),
            )
            .order_by(Protein.created_at.desc())
            .limit(limit)
        )
        found = [
            (acc, length, h) for acc, length, h in rows.all() if acc
        ]
        if not found:
            return []

        names = await self._names([acc for acc, _, _ in found])
        return [
            CatalogEntry(
                uniprot_id=acc,
                gene=names.get(acc, ("", ""))[0] or acc,
                name=names.get(acc, ("", ""))[1],
                length=length,
                sequence_hash=h,
            )
            for acc, length, h in found
        ]

    async def _names(self, accessions: list[str]) -> dict[str, tuple[str, str]]:
        """Gene symbol + protein name per accession, one request for the lot."""
        missing = [a for a in accessions if a not in _NAME_CACHE]
        if missing and self.uniprot is not None:
            try:
                # Only successful lookups are cached. Caching a miss would be
                # tempting to avoid repeat queries, but it means a single
                # UniProt hiccup leaves every name blank until the process
                # restarts. Re-querying after a failure is cheap and self-heals.
                _NAME_CACHE.update(await self.uniprot.fetch_entry_names(missing))
            except Exception:  # noqa: BLE001
                pass  # names are cosmetic; the accession is a fine fallback
        return {a: _NAME_CACHE[a] for a in accessions if a in _NAME_CACHE}
