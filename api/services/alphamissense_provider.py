"""
AlphaMissense provider — looks up a missense variant's pathogenicity from the
local SQLite built by scripts/build_alphamissense_db.py.

Gracefully degrades: if the DB file isn't present (the ~1.2GB dataset is
optional), every lookup returns None and AlphaMissense is simply omitted from
annotations. The read-only connection is opened once and cached at module
level for the life of the API process.
"""

import gzip
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from config import get_settings

_conn: sqlite3.Connection | None = None
_checked = False


def _connection() -> sqlite3.Connection | None:
    global _conn, _checked
    if _checked:
        return _conn
    _checked = True
    path = Path(get_settings().alphamissense_db_path)
    if path.exists():
        _conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    return _conn


def reset_connection_cache() -> None:
    """Test hook — forces the next lookup to re-open the configured DB."""
    global _conn, _checked
    if _conn is not None:
        _conn.close()
    _conn = None
    _checked = False


@dataclass(frozen=True)
class AlphaMissensePrediction:
    score: float       # am_pathogenicity, 0-1 (higher = more pathogenic)
    classification: str  # am_class, e.g. "likely_pathogenic" | "benign" | "ambiguous"


class AlphaMissenseProvider:
    def lookup(
        self, uniprot_id: str, variant: str
    ) -> AlphaMissensePrediction | None:
        """Return the AlphaMissense call for e.g. ('P04637', 'R175H'), or None."""
        conn = _connection()
        if conn is None:
            return None
        row = conn.execute(
            "SELECT block FROM am WHERE uniprot_id = ?", (uniprot_id,)
        ).fetchone()
        if row is None:
            return None
        for line in gzip.decompress(row[0]).decode("ascii").splitlines():
            var, score, cls = line.split("\t")
            if var == variant:
                return AlphaMissensePrediction(score=float(score), classification=cls)
        return None
