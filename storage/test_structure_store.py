"""Unit tests for LocalStructureStore. No network, no DB — pure filesystem."""

import pytest

from storage.structure_store import LocalStructureStore

SEQ_HASH = "ab" + "0" * 62
PDB_BYTES = b"HEADER    TEST\nATOM      1  N   MET A   1      0.000   0.000   0.000\nEND\n"


@pytest.fixture
def store(tmp_path):
    return LocalStructureStore(root=tmp_path)


def test_build_uri_is_deterministic(store):
    assert store.build_uri(SEQ_HASH, "pdb") == store.build_uri(SEQ_HASH, "pdb")


def test_write_then_read_roundtrip(store):
    uri = store.write(SEQ_HASH, "pdb", PDB_BYTES)
    assert store.exists(uri)
    assert store.read(uri) == PDB_BYTES


def test_write_shards_by_hash_prefix(store, tmp_path):
    store.write(SEQ_HASH, "pdb", PDB_BYTES)
    expected = tmp_path / "ab" / f"{SEQ_HASH}.pdb"
    assert expected.is_file()


def test_exists_false_for_missing_uri(store):
    assert not store.exists(store.build_uri("0" * 64, "pdb"))


def test_formats_are_stored_separately(store):
    uri_pdb = store.write(SEQ_HASH, "pdb", b"PDB")
    uri_cif = store.write(SEQ_HASH, "cif", b"CIF")
    assert uri_pdb != uri_cif
    assert store.read(uri_pdb) == b"PDB"
    assert store.read(uri_cif) == b"CIF"
