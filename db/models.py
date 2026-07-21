"""
SQLAlchemy 2.0 async ORM models. Every table has a single-purpose role:

  proteins        — canonical sequences, indexed by sequence_hash
  score_matrices  — (protein, model) -> pointer into object storage
  structures      — (protein) -> structure file location + SIFTS map ref
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
    structure: Mapped["Structure | None"] = relationship(back_populates="protein", uselist=False)


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
    __tablename__ = "structures"

    sequence_hash: Mapped[str] = mapped_column(
        String(64), ForeignKey("proteins.sequence_hash"), primary_key=True
    )
    structure_uri: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)  # "alphafold" | "rcsb"
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # upstream provenance
    sifts_map_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    protein: Mapped[Protein] = relationship(back_populates="structure")


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
