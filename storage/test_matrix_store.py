"""Unit tests for LocalMatrixStore. No network, no DB — pure filesystem."""

import numpy as np
import pytest

from storage.matrix_store import LocalMatrixStore


@pytest.fixture
def store(tmp_path):
    return LocalMatrixStore(root=tmp_path)


def test_build_uri_is_deterministic(store):
    uri1 = store.build_uri("esm2_t33_650M_UR50D", "abcdef0123")
    uri2 = store.build_uri("esm2_t33_650M_UR50D", "abcdef0123")
    assert uri1 == uri2


def test_write_then_read_roundtrip(store):
    matrix = np.random.default_rng(0).normal(size=(100, 20)).astype(np.float32)
    uri = store.write("esm2_t33_650M_UR50D", "abcdef" * 10 + "abcd", matrix)
    assert store.exists(uri)

    loaded = store.read(uri)
    np.testing.assert_allclose(loaded, matrix, rtol=0, atol=0)


def test_write_shards_by_hash_prefix(store, tmp_path):
    matrix = np.zeros((10, 20), dtype=np.float32)
    seq_hash = "ab" + "0" * 62
    store.write("esm2_t33_650M_UR50D", seq_hash, matrix)
    expected_dir = tmp_path / "esm2_t33_650M_UR50D" / "ab"
    assert expected_dir.is_dir()
    assert (expected_dir / f"{seq_hash}.npz").is_file()


def test_exists_false_for_missing_uri(store):
    uri = store.build_uri("esm2_t33_650M_UR50D", "0" * 64)
    assert not store.exists(uri)


def test_different_models_have_separate_matrices(store):
    matrix_a = np.ones((10, 20), dtype=np.float32)
    matrix_b = np.zeros((10, 20), dtype=np.float32)
    seq_hash = "c" * 64
    uri_a = store.write("model_a", seq_hash, matrix_a)
    uri_b = store.write("model_b", seq_hash, matrix_b)
    assert uri_a != uri_b
    np.testing.assert_array_equal(store.read(uri_a), matrix_a)
    np.testing.assert_array_equal(store.read(uri_b), matrix_b)
