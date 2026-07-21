"""
Unit tests for the AlphaMissense provider + its wiring into AnnotationService.
Uses a tiny fixture SQLite in the same format as the real build — no network,
no 1.2GB dataset needed.
"""

import gzip
import sqlite3

import pytest

from api.services.alphamissense_provider import (
    AlphaMissenseProvider,
    reset_connection_cache,
)
from api.services.annotation_service import AnnotationService
from config import get_settings
from domain.derive import Variant


def _build_fixture_db(path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE am (uniprot_id TEXT PRIMARY KEY, block BLOB)")
    block = gzip.compress(
        "\n".join(
            ["R175H\t0.9821\tlikely_pathogenic", "P72R\t0.0812\tlikely_benign"]
        ).encode("ascii")
    )
    conn.execute("INSERT INTO am VALUES (?, ?)", ("P04637", block))
    conn.commit()
    conn.close()


@pytest.fixture
def am_db(tmp_path, monkeypatch):
    db = tmp_path / "am.sqlite"
    _build_fixture_db(db)
    monkeypatch.setenv("ALPHAMISSENSE_DB_PATH", str(db))
    get_settings.cache_clear()
    reset_connection_cache()
    yield db
    get_settings.cache_clear()
    reset_connection_cache()


def test_lookup_hit(am_db):
    r = AlphaMissenseProvider().lookup("P04637", "R175H")
    assert r is not None
    assert r.classification == "likely_pathogenic"
    assert abs(r.score - 0.9821) < 1e-6


def test_lookup_unknown_variant(am_db):
    assert AlphaMissenseProvider().lookup("P04637", "R175C") is None


def test_lookup_unknown_protein(am_db):
    assert AlphaMissenseProvider().lookup("ZZZZZZ", "R175H") is None


def test_absent_db_degrades_gracefully(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPHAMISSENSE_DB_PATH", str(tmp_path / "missing.sqlite"))
    get_settings.cache_clear()
    reset_connection_cache()
    try:
        assert AlphaMissenseProvider().lookup("P04637", "R175H") is None
    finally:
        get_settings.cache_clear()
        reset_connection_cache()


class _NoEbiClient:
    async def fetch_variants(self, accession):
        return []


@pytest.mark.asyncio
async def test_annotation_includes_alphamissense_even_without_ebi(am_db):
    svc = AnnotationService(_NoEbiClient(), alphamissense=AlphaMissenseProvider())
    ann = await svc.annotate("P04637", Variant.parse("R175H"))
    assert ann is not None  # AlphaMissense alone is enough to annotate
    preds = {p.algorithm: p for p in ann.predictions}
    assert "AlphaMissense" in preds
    assert preds["AlphaMissense"].prediction == "likely_pathogenic"
