"""
Centralized configuration for both API and worker processes. Reads from
environment variables, with sensible dev defaults. Both processes import
`get_settings()` from here — never read os.environ directly elsewhere.

This module is intentionally top-level (a sibling of domain/ and
contracts/), not nested under api/, because both the API and worker
processes need it and neither should pull in the other's dependencies.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ---
    # asyncpg for the api/worker code paths, sync psycopg2 driver for Alembic migrations.
    database_url: str = Field(
        default="postgresql+asyncpg://protein:protein_dev_password@localhost:5432/protein_variant_db"
    )

    # --- Redis / queue ---
    redis_url: str = Field(default="redis://localhost:6379")

    # --- Matrix storage ---
    # "local" = filesystem under matrix_storage_path (dev/testing).
    # "gcs"   = Google Cloud Storage bucket (production).
    matrix_storage_backend: str = Field(default="local")
    matrix_storage_path: Path = Field(default=Path("./data/matrices"))
    matrix_storage_bucket: str | None = Field(default=None)

    # --- External APIs ---
    uniprot_api_base: str = "https://rest.uniprot.org"
    alphafold_db_base: str = "https://alphafold.ebi.ac.uk/files"
    rcsb_api_base: str = "https://data.rcsb.org/rest/v1"
    http_timeout_seconds: float = 30.0

    # --- Model ---
    default_model_id: str = "esm2_t33_650M_UR50D"

    @property
    def alembic_database_url(self) -> str:
        """Sync driver URL for Alembic. Swaps asyncpg -> psycopg2 automatically."""
        return self.database_url.replace("+asyncpg", "+psycopg2")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
