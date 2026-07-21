"""
Matrix persistence abstraction. All callers depend on this Protocol,
never on a concrete implementation. Adding GCS later is a new class that
satisfies the same interface — zero caller-side changes.

Format on disk: numpy compressed .npz files. A 1000-residue matrix is
~40KB compressed. Small, portable, no schema drift risk.

Top-level (not nested under api/) so the worker process can write
matrices here without importing api-only code.
"""

import io
from pathlib import Path
from typing import Protocol

import numpy as np

from config import get_settings


class MatrixStore(Protocol):
    """The frozen storage contract. Every backend implements exactly this."""

    def build_uri(self, model_id: str, sequence_hash: str) -> str:
        ...

    def write(self, model_id: str, sequence_hash: str, matrix: np.ndarray) -> str:
        ...

    def read(self, uri: str) -> np.ndarray:
        ...

    def exists(self, uri: str) -> bool:
        ...


class LocalMatrixStore:
    """Filesystem-backed store for local development and tests."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, model_id: str, sequence_hash: str) -> Path:
        return self.root / model_id / sequence_hash[:2] / f"{sequence_hash}.npz"

    def build_uri(self, model_id: str, sequence_hash: str) -> str:
        return f"file://{self._path_for(model_id, sequence_hash).resolve()}"

    def write(self, model_id: str, sequence_hash: str, matrix: np.ndarray) -> str:
        path = self._path_for(model_id, sequence_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO()
        np.savez_compressed(buffer, matrix=matrix.astype(np.float32))
        path.write_bytes(buffer.getvalue())
        return self.build_uri(model_id, sequence_hash)

    def read(self, uri: str) -> np.ndarray:
        path = Path(uri.removeprefix("file://"))
        with np.load(path) as data:
            return data["matrix"]

    def exists(self, uri: str) -> bool:
        path = Path(uri.removeprefix("file://"))
        return path.is_file()


class GCSMatrixStore:
    """Google Cloud Storage backend. Identical interface to LocalMatrixStore."""

    def __init__(self, bucket_name: str) -> None:
        from google.cloud import storage  # type: ignore

        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)
        self.bucket_name = bucket_name

    def _blob_name(self, model_id: str, sequence_hash: str) -> str:
        return f"matrices/{model_id}/{sequence_hash[:2]}/{sequence_hash}.npz"

    def build_uri(self, model_id: str, sequence_hash: str) -> str:
        return f"gs://{self.bucket_name}/{self._blob_name(model_id, sequence_hash)}"

    def write(self, model_id: str, sequence_hash: str, matrix: np.ndarray) -> str:
        buffer = io.BytesIO()
        np.savez_compressed(buffer, matrix=matrix.astype(np.float32))
        buffer.seek(0)
        blob = self.bucket.blob(self._blob_name(model_id, sequence_hash))
        blob.upload_from_file(buffer, content_type="application/octet-stream")
        return self.build_uri(model_id, sequence_hash)

    def read(self, uri: str) -> np.ndarray:
        assert uri.startswith(f"gs://{self.bucket_name}/"), f"URI mismatch: {uri}"
        blob_name = uri.removeprefix(f"gs://{self.bucket_name}/")
        blob = self.bucket.blob(blob_name)
        buffer = io.BytesIO(blob.download_as_bytes())
        with np.load(buffer) as data:
            return data["matrix"]

    def exists(self, uri: str) -> bool:
        blob_name = uri.removeprefix(f"gs://{self.bucket_name}/")
        return self.bucket.blob(blob_name).exists()


def get_matrix_store() -> MatrixStore:
    """Single factory. Returns the store selected by configuration."""
    settings = get_settings()
    if settings.matrix_storage_backend == "local":
        return LocalMatrixStore(settings.matrix_storage_path)
    if settings.matrix_storage_backend == "gcs":
        if not settings.matrix_storage_bucket:
            raise RuntimeError("MATRIX_STORAGE_BUCKET must be set when backend=gcs")
        return GCSMatrixStore(settings.matrix_storage_bucket)
    raise RuntimeError(f"Unknown matrix_storage_backend: {settings.matrix_storage_backend}")
