"""
Structure file persistence — the byte-blob sibling of matrix_store.

Where MatrixStore holds numpy .npz arrays, StructureStore holds raw
structure files (mmCIF/.pdb) fetched from AlphaFold DB or RCSB. Same
Protocol shape, same local/GCS split, same top-level placement so both
the API (serving files to the Mol* viewer) and the worker (reading files
for DSSP) can use it without importing api-only code.

Keyed by (sequence_hash, format) so a protein can, in principle, carry
both a .pdb and a .cif copy — the current pipeline stores one.
"""

from pathlib import Path
from typing import Protocol

from config import get_settings


class StructureStore(Protocol):
    """The frozen storage contract. Every backend implements exactly this."""

    def build_uri(self, sequence_hash: str, fmt: str) -> str:
        ...

    def write(self, sequence_hash: str, fmt: str, data: bytes) -> str:
        ...

    def read(self, uri: str) -> bytes:
        ...

    def exists(self, uri: str) -> bool:
        ...


class LocalStructureStore:
    """Filesystem-backed store for local development and tests."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, sequence_hash: str, fmt: str) -> Path:
        return self.root / sequence_hash[:2] / f"{sequence_hash}.{fmt}"

    def build_uri(self, sequence_hash: str, fmt: str) -> str:
        return f"file://{self._path_for(sequence_hash, fmt).resolve()}"

    def write(self, sequence_hash: str, fmt: str, data: bytes) -> str:
        path = self._path_for(sequence_hash, fmt)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self.build_uri(sequence_hash, fmt)

    def read(self, uri: str) -> bytes:
        return Path(uri.removeprefix("file://")).read_bytes()

    def exists(self, uri: str) -> bool:
        return Path(uri.removeprefix("file://")).is_file()


class GCSStructureStore:
    """Google Cloud Storage backend. Identical interface to LocalStructureStore."""

    def __init__(self, bucket_name: str) -> None:
        from google.cloud import storage  # type: ignore

        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)
        self.bucket_name = bucket_name

    def _blob_name(self, sequence_hash: str, fmt: str) -> str:
        return f"structures/{sequence_hash[:2]}/{sequence_hash}.{fmt}"

    def build_uri(self, sequence_hash: str, fmt: str) -> str:
        return f"gs://{self.bucket_name}/{self._blob_name(sequence_hash, fmt)}"

    def write(self, sequence_hash: str, fmt: str, data: bytes) -> str:
        blob = self.bucket.blob(self._blob_name(sequence_hash, fmt))
        blob.upload_from_string(data, content_type="chemical/x-pdb")
        return self.build_uri(sequence_hash, fmt)

    def read(self, uri: str) -> bytes:
        assert uri.startswith(f"gs://{self.bucket_name}/"), f"URI mismatch: {uri}"
        blob_name = uri.removeprefix(f"gs://{self.bucket_name}/")
        return self.bucket.blob(blob_name).download_as_bytes()

    def exists(self, uri: str) -> bool:
        blob_name = uri.removeprefix(f"gs://{self.bucket_name}/")
        return self.bucket.blob(blob_name).exists()


def get_structure_store() -> StructureStore:
    """Single factory. Returns the store selected by configuration."""
    settings = get_settings()
    if settings.matrix_storage_backend == "local":
        return LocalStructureStore(settings.structure_storage_path)
    if settings.matrix_storage_backend == "gcs":
        if not settings.matrix_storage_bucket:
            raise RuntimeError("MATRIX_STORAGE_BUCKET must be set when backend=gcs")
        return GCSStructureStore(settings.matrix_storage_bucket)
    raise RuntimeError(f"Unknown matrix_storage_backend: {settings.matrix_storage_backend}")
