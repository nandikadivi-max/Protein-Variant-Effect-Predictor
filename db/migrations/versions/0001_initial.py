"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-20

Creates the four persistent tables: proteins, score_matrices, structures, jobs.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "proteins",
        sa.Column("sequence_hash", sa.String(64), primary_key=True),
        sa.Column("sequence", sa.Text, nullable=False),
        sa.Column("length", sa.Integer, nullable=False),
        sa.Column("uniprot_id", sa.String(20), nullable=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_proteins_uniprot_id", "proteins", ["uniprot_id"])

    op.create_table(
        "score_matrices",
        sa.Column(
            "sequence_hash",
            sa.String(64),
            sa.ForeignKey("proteins.sequence_hash"),
            primary_key=True,
        ),
        sa.Column("model_id", sa.String(64), primary_key=True),
        sa.Column("matrix_uri", sa.Text, nullable=False),
        sa.Column("model_revision", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "structures",
        sa.Column(
            "sequence_hash",
            sa.String(64),
            sa.ForeignKey("proteins.sequence_hash"),
            primary_key=True,
        ),
        sa.Column("structure_uri", sa.Text, nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("sifts_map_uri", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(36), primary_key=True),
        sa.Column(
            "sequence_hash",
            sa.String(64),
            sa.ForeignKey("proteins.sequence_hash"),
            nullable=False,
        ),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_sequence_hash", "jobs", ["sequence_hash"])
    op.create_index("ix_jobs_status", "jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_sequence_hash", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("structures")
    op.drop_table("score_matrices")
    op.drop_index("ix_proteins_uniprot_id", table_name="proteins")
    op.drop_table("proteins")
