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
    # The structure store shares this same backend + bucket selection; only
    # the local filesystem path differs (structures are raw .pdb/.cif files,
    # not numpy arrays, so they live under their own directory).
    matrix_storage_backend: str = Field(default="local")
    matrix_storage_path: Path = Field(default=Path("./data/matrices"))
    matrix_storage_bucket: str | None = Field(default=None)
    structure_storage_path: Path = Field(default=Path("./data/structures"))

    # --- External APIs ---
    uniprot_api_base: str = "https://rest.uniprot.org"
    # AlphaFold bumps its model version periodically (v4 -> v6 -> ...), so we
    # resolve the real file URL through the prediction API rather than
    # hardcoding a version into the path.
    alphafold_api_base: str = "https://alphafold.ebi.ac.uk/api"
    rcsb_api_base: str = "https://data.rcsb.org/rest/v1"
    rcsb_files_base: str = "https://files.rcsb.org/download"
    # EBI Proteins API — per-protein variant annotations (clinical significance
    # aggregated from ClinVar/Ensembl/UniProt/NCI-TCGA, plus SIFT/PolyPhen).
    proteins_api_base: str = "https://www.ebi.ac.uk/proteins/api"
    http_timeout_seconds: float = 30.0

    # --- AlphaMissense ---
    # Optional local SQLite built from the bulk aa-substitutions dataset (see
    # scripts/build_alphamissense_db.py). When present, missense predictions are
    # added to annotations; when absent, AlphaMissense is silently skipped.
    alphamissense_db_path: Path = Field(default=Path("./data/alphamissense.sqlite"))

    # --- Model ---
    default_model_id: str = "esm2_t33_650M_UR50D"

    # --- Deployment ---
    # Comma-separated allowed CORS origins (the deployed frontend origin(s)).
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def alembic_database_url(self) -> str:
        """Sync driver URL for Alembic. Swaps asyncpg -> psycopg2 automatically."""
        return self.database_url.replace("+asyncpg", "+psycopg2")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
