"""
SQLAlchemy 2.0 async ORM models. Every table has a single-purpose role:

  proteins        — canonical sequences, indexed by sequence_hash
  score_matrices  — (protein, model) -> pointer into object storage
  structures      — (protein, provider) -> file location + SIFTS map ref
  jobs            — durable job records (status, timing, errors)

Top-level (not nested under api/) because the worker process also needs
these models to persist computed matrices — same reasoning as domain/
and contracts/ being shared, torch-free packages.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Protein(Base):
    __tablename__ = "proteins"

    sequence_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    sequence: Mapped[str] = mapped_column(Text, nullable=False)
    length: Mapped[int] = mapped_column(Integer, nullable=False)
    uniprot_id: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    matrices: Mapped[list["ScoreMatrix"]] = relationship(back_populates="protein")
    structures: Mapped[list["Structure"]] = relationship(back_populates="protein")


class ScoreMatrix(Base):
    __tablename__ = "score_matrices"

    sequence_hash: Mapped[str] = mapped_column(
        String(64), ForeignKey("proteins.sequence_hash"), primary_key=True
    )
    model_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    matrix_uri: Mapped[str] = mapped_column(Text, nullable=False)
    model_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    protein: Mapped[Protein] = relationship(back_populates="matrices")


class Structure(Base):
    """
    One 3D structure for a protein, per provider.

    Keyed by (sequence_hash, provider) rather than sequence_hash alone, so a
    protein can hold its predicted AlphaFold model and an experimental PDB
    entry at the same time. While sequence_hash was the whole key, resolving a
    PDB id overwrote the prediction for every visitor at once, and which one
    you saw depended on what somebody else had searched.
    """

    __tablename__ = "structures"

    sequence_hash: Mapped[str] = mapped_column(
        String(64), ForeignKey("proteins.sequence_hash"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(
        String(16), primary_key=True
    )  # "alphafold" | "rcsb"
    # Nullable: a PDB-sourced row is recorded at resolve time (with pdb_id +
    # sifts_map_uri) but its file is fetched from RCSB lazily on first view.
    structure_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdb_id: Mapped[str | None] = mapped_column(String(8), nullable=True)  # set when provider=rcsb
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # upstream provenance
    sifts_map_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    protein: Mapped[Protein] = relationship(back_populates="structures")


class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sequence_hash: Mapped[str] = mapped_column(
        String(64), ForeignKey("proteins.sequence_hash"), nullable=False, index=True
    )
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
